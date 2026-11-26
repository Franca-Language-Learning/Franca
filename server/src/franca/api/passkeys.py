"""Routes for adding passkeys and signing in with them (story E02-001).

Each WebAuthn ceremony has two requests: the browser asks for options, then sends the device's answer. The challenge
in the options is kept on the server for up to five minutes, with what it is for and, when a passkey is added, for
whom. The browser's signed cookie (franca_oauth) holds a random id for it. The challenge is removed when the answer
arrives, so an answer can be used once, also with a copy of the earlier cookie.

The challenges are kept in memory. Franca runs as one server process; a challenge that is waiting when the service
restarts is lost, and the learner starts again.
"""

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from franca import identity
from franca.api.auth import Db, Me, RecentlySignedIn, SignedIn, set_session_cookie
from franca.platform import Settings, utc_now

CHALLENGE_KEY = "passkey_challenge"
CHALLENGE_SECONDS = 300
# Sign-in options can be asked for without signing in, so the number of waiting challenges is limited; the oldest
# is dropped first.
MAX_CHALLENGES = 1000
NOT_ACCEPTED = "passkey-not-accepted"
UNKNOWN = "passkey-unknown"


@dataclass(frozen=True, slots=True)
class _Waiting:
    purpose: str
    learner_uuid: str | None
    challenge: bytes
    expires: float


class ChallengeStore:
    """Challenges waiting for an answer, by a random id. take() removes the challenge, so it can be used once."""

    def __init__(self) -> None:
        self._waiting: OrderedDict[str, _Waiting] = OrderedDict()
        self._lock = threading.Lock()

    def keep(self, purpose: str, challenge: bytes, learner: identity.Learner | None) -> str:
        key = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            for old in [k for k, w in self._waiting.items() if w.expires <= now]:
                del self._waiting[old]
            while len(self._waiting) >= MAX_CHALLENGES:
                self._waiting.popitem(last=False)
            self._waiting[key] = _Waiting(purpose, learner.uuid if learner else None, challenge, now + CHALLENGE_SECONDS)
        return key

    def take(self, key: object, purpose: str, learner: identity.Learner | None) -> bytes | None:
        with self._lock:
            waiting = self._waiting.pop(key, None) if isinstance(key, str) else None
        if waiting is None or waiting.expires <= time.monotonic():
            return None
        if waiting.purpose != purpose or waiting.learner_uuid != (learner.uuid if learner else None):
            return None
        return waiting.challenge


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


def _keep_challenge(
    request: Request, store: ChallengeStore, purpose: str, challenge: bytes, learner: identity.Learner | None = None
) -> None:
    request.session[CHALLENGE_KEY] = store.keep(purpose, challenge, learner)


def _take_challenge(request: Request, store: ChallengeStore, purpose: str, learner: identity.Learner | None = None) -> bytes:
    """The challenge that was given for this purpose (and learner). It is removed, so it can be used once."""
    challenge = store.take(request.session.pop(CHALLENGE_KEY, None), purpose, learner)
    if challenge is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no-passkey-options")
    return challenge


def passkey_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["identity"])
    rp = identity.relying_party(settings.public_url)
    store = ChallengeStore()
    unauthorised: dict[int | str, dict[str, Any]] = {401: {"description": "Not signed in"}}

    @router.post(
        "/passkeys/options",
        operation_id="getPasskeyRegistrationOptions",
        summary="Options for adding a passkey on this device",
        response_model=PublicKeyOptions,
        responses={
            **unauthorised,
            403: {"description": "The learner signed in more than 15 minutes ago (sign-in-again), or has the most passkeys allowed"},
        },
    )
    def registration_options(request: Request, db: Db, learner: RecentlySignedIn) -> PublicKeyOptions:
        try:
            started = identity.passkey_registration_options(db, learner, rp)
        except identity.NotAllowed as error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
        _keep_challenge(request, store, "add", started.challenge, learner)
        return PublicKeyOptions(publicKey=started.options)

    @router.post(
        "/passkeys",
        operation_id="addPasskey",
        summary="Adds a passkey with the device's answer to the options",
        status_code=status.HTTP_201_CREATED,
        response_model=PasskeyOut,
        responses={
            **unauthorised,
            400: {"description": "No options were asked for, or the answer failed a check"},
            403: {"description": "The learner signed in more than 15 minutes ago (sign-in-again)"},
        },
    )
    def add(body: PasskeyRequest, request: Request, db: Db, learner: RecentlySignedIn) -> PasskeyOut:
        challenge = _take_challenge(request, store, "add", learner)
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
        _keep_challenge(request, store, "sign_in", started.challenge)
        return PublicKeyOptions(publicKey=started.options)

    @router.post(
        "/auth/passkey",
        operation_id="signInWithPasskey",
        summary="Signs in with the device's answer to the options",
        response_model=Me,
        responses={
            400: {"description": "No options were asked for"},
            401: {
                "description": "Franca does not have the passkey (passkey-unknown), the answer failed a check, or the account is disabled"
            },
        },
    )
    def sign_in(
        body: SignInRequest, request: Request, response: Response, db: Db, franca_session: Annotated[str | None, Cookie()] = None
    ) -> Me:
        challenge = _take_challenge(request, store, "sign_in")
        now = utc_now()
        try:
            learner = identity.sign_in_with_passkey(db, body.credential, challenge=challenge, rp=rp, now=now)
            if franca_session:
                identity.end_session(db, franca_session, now)  # an earlier session in this browser is closed
            token = identity.start_session(db, learner, request.headers.get("user-agent"), now, passkey_id=str(body.credential["rawId"]))
        except identity.PasskeyUnknown:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, UNKNOWN) from None
        except identity.PasskeyNotAccepted:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, NOT_ACCEPTED) from None
        except identity.SignInRefused as refusal:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, refusal.reason) from None
        set_session_cookie(response, settings, token)
        return Me(displayName=learner.display_name, role=learner.role)

    return router
