"""Routes for adding passkeys and signing in with them (story E02-001).

Each WebAuthn ceremony has two requests: the browser asks for options, then sends the device's answer. The challenge
in the options is kept in the short-lived signed cookie (franca_oauth, at most 10 minutes) with what it is for, and
it is removed when the answer arrives, so an answer can be used once.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError, OperationalError
from webauthn import base64url_to_bytes
from webauthn.helpers import bytes_to_base64url

from franca import identity
from franca.api.auth import Db, Me, SignedIn, set_session_cookie
from franca.platform import Settings, utc_now

CHALLENGE_KEY = "passkey_challenge"
NOT_ACCEPTED = "passkey-not-accepted"


class PublicKeyOptions(BaseModel):
    """The options for navigator.credentials.create() or .get(), in the JSON form that the browser reads."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "publicKey": {
                        "challenge": "dGVzdC1jaGFsbGVuZ2UtMzItYnl0ZXMtbG9uZy0tLS0",
                        "rpId": "franca.example.ts.net",
                        "timeout": 60000,
                        "allowCredentials": [],
                        "userVerification": "preferred",
                    }
                }
            ]
        }
    )

    publicKey: dict[str, Any]


class PasskeyRequest(BaseModel):
    credential: dict[str, Any] = Field(description="The device's answer: the PublicKeyCredential in its JSON form")
    label: str | None = Field(default=None, max_length=60, description="A name the learner chooses, such as Phone")


class SignInRequest(BaseModel):
    credential: dict[str, Any] = Field(description="The device's answer: the PublicKeyCredential in its JSON form")


class PasskeyOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "Ab3kN0pQ2rS4tU6vW8xY0zA1bC3dE5fG7hI9jK1lM3n",
                    "label": "Phone",
                    "createdAt": "2026-12-01T09:00:00.000Z",
                    "lastUsedAt": None,
                    "synced": True,
                }
            ]
        }
    )

    id: str
    label: str | None
    createdAt: str
    lastUsedAt: str | None
    synced: bool = Field(description="Kept in a password manager or cloud account, so it is on more than one device")


class PasskeyList(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"passkeys": PasskeyOut.model_config["json_schema_extra"]["examples"]}]})  # type: ignore[index]

    passkeys: list[PasskeyOut]


def _out(passkey: identity.Passkey) -> PasskeyOut:
    return PasskeyOut(
        id=passkey.passkey_id, label=passkey.label, createdAt=passkey.created_at, lastUsedAt=passkey.last_used_at, synced=passkey.synced
    )


def _keep_challenge(request: Request, purpose: str, challenge: bytes, learner: identity.Learner | None = None) -> None:
    request.session[CHALLENGE_KEY] = {
        "purpose": purpose,
        "challenge": bytes_to_base64url(challenge),
        "learner": learner.uuid if learner else None,
    }


def _take_challenge(request: Request, purpose: str, learner: identity.Learner | None = None) -> bytes:
    """The challenge that was given for this purpose (and learner). It is removed, so it can be used once."""
    kept = request.session.pop(CHALLENGE_KEY, None)
    if not isinstance(kept, dict) or kept.get("purpose") != purpose or kept.get("learner") != (learner.uuid if learner else None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no-passkey-options")
    return base64url_to_bytes(str(kept["challenge"]))


def passkey_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["identity"])
    rp = identity.relying_party(settings.public_url)
    unauthorised: dict[int | str, dict[str, Any]] = {401: {"description": "Not signed in"}}

    @router.post(
        "/passkeys/options",
        operation_id="getPasskeyRegistrationOptions",
        summary="Options for adding a passkey on this device",
        response_model=PublicKeyOptions,
        responses={**unauthorised, 403: {"description": "The learner has the most passkeys allowed"}},
    )
    def registration_options(request: Request, db: Db, learner: SignedIn) -> PublicKeyOptions:
        try:
            started = identity.passkey_registration_options(db, learner, rp)
        except identity.NotAllowed as error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
        _keep_challenge(request, "add", started.challenge, learner)
        return PublicKeyOptions(publicKey=started.options)

    @router.post(
        "/passkeys",
        operation_id="addPasskey",
        summary="Adds a passkey with the device's answer to the options",
        status_code=status.HTTP_201_CREATED,
        response_model=PasskeyOut,
        responses={**unauthorised, 400: {"description": "No options were asked for, or the answer failed a check"}},
    )
    def add(body: PasskeyRequest, request: Request, db: Db, learner: SignedIn) -> PasskeyOut:
        challenge = _take_challenge(request, "add", learner)
        try:
            passkey = identity.add_passkey(db, learner, body.credential, challenge=challenge, rp=rp, label=body.label, now=utc_now())
        except identity.PasskeyNotAccepted, IntegrityError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_ACCEPTED) from None
        except identity.NotAllowed as error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
        return _out(passkey)

    @router.get(
        "/passkeys",
        operation_id="listPasskeys",
        summary="The signed-in learner's passkeys",
        response_model=PasskeyList,
        responses=unauthorised,
    )
    def passkeys(db: Db, learner: SignedIn) -> PasskeyList:
        return PasskeyList(passkeys=[_out(p) for p in identity.list_passkeys(db, learner)])

    @router.delete(
        "/passkeys/{passkeyId}",
        operation_id="removePasskey",
        summary="Removes one of the signed-in learner's passkeys",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        responses={**unauthorised, 404: {"description": "The learner has no passkey with this id"}},
    )
    def remove(passkeyId: str, db: Db, learner: SignedIn) -> Response:  # noqa: N803 - the name in the URL
        try:
            identity.remove_passkey(db, learner, passkeyId, utc_now())
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such passkey") from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/auth/passkey/options",
        operation_id="getPasskeySignInOptions",
        summary="Options for signing in with a passkey",
        response_model=PublicKeyOptions,
    )
    def sign_in_options(request: Request) -> PublicKeyOptions:
        started = identity.passkey_sign_in_options(rp)
        _keep_challenge(request, "sign_in", started.challenge)
        return PublicKeyOptions(publicKey=started.options)

    @router.post(
        "/auth/passkey",
        operation_id="signInWithPasskey",
        summary="Signs in with the device's answer to the options",
        response_model=Me,
        responses={
            400: {"description": "No options were asked for"},
            401: {"description": "The passkey was not accepted, or the account is disabled"},
        },
    )
    def sign_in(
        body: SignInRequest, request: Request, response: Response, db: Db, franca_session: Annotated[str | None, Cookie()] = None
    ) -> Me:
        challenge = _take_challenge(request, "sign_in")
        now = utc_now()
        try:
            learner = identity.sign_in_with_passkey(db, body.credential, challenge=challenge, rp=rp, now=now)
            if franca_session:
                identity.end_session(db, franca_session, now)  # an earlier session in this browser is closed
            token = identity.start_session(db, learner, request.headers.get("user-agent"), now)
        except identity.PasskeyNotAccepted:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, NOT_ACCEPTED) from None
        except identity.SignInRefused as refusal:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, refusal.reason) from None
        except OperationalError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The database is busy; try again") from None
        set_session_cookie(response, settings, token)
        return Me(displayName=learner.display_name, role=learner.role)

    return router
