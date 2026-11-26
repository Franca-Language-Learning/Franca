"""Routes for signing in with Google, the signed-in learner, signing out and invitations (story E02-001).

Sign-in with Google uses OpenID Connect with PKCE through Authlib. Authlib checks the state, the nonce and the
ID token's signature, issuer, audience and expiry. The state of a sign-in in progress is kept in a short-lived signed
cookie (franca_oauth); the sign-in session is a random token in the franca_session cookie, of which only a hash is
stored.
"""

from collections.abc import Iterator
from typing import Annotated, Any

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from joserfc.errors import JoseError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine

from franca import identity
from franca.platform import Settings, utc_now

SESSION_COOKIE = "franca_session"
GOOGLE_DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"


class Me(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"displayName": "Nik", "role": "owner"}]})

    displayName: str  # noqa: N815 (the API uses camelCase)
    role: str


class InvitationRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"email": "partner@example.org"}]})

    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)


class InvitationOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "partner@example.org",
                    "createdAt": "2026-12-01T09:00:00.000Z",
                    "expiresAt": "2026-12-15T09:00:00.000Z",
                    "status": "open",
                }
            ]
        }
    )

    email: str
    createdAt: str  # noqa: N815
    expiresAt: str  # noqa: N815
    status: str


class InvitationList(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "invitations": [
                        {
                            "email": "partner@example.org",
                            "createdAt": "2026-12-01T09:00:00.000Z",
                            "expiresAt": "2026-12-15T09:00:00.000Z",
                            "status": "open",
                        }
                    ]
                }
            ]
        }
    )

    invitations: list[InvitationOut]


def _invitation(invitation: identity.Invitation) -> InvitationOut:
    return InvitationOut(email=invitation.email, createdAt=invitation.created_at, expiresAt=invitation.expires_at, status=invitation.status)


def connection(request: Request) -> Iterator[Connection]:
    engine: Engine = request.app.state.engine
    with engine.begin() as conn:
        yield conn


Db = Annotated[Connection, Depends(connection)]


def current_learner(db: Db, franca_session: Annotated[str | None, Cookie()] = None) -> identity.Learner:
    learner = identity.learner_for_session(db, franca_session, utc_now()) if franca_session else None
    if learner is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return learner


SignedIn = Annotated[identity.Learner, Depends(current_learner)]


def auth_router(settings: Settings, oauth: OAuth | None) -> APIRouter:
    router = APIRouter(tags=["identity"])

    def refused(reason: str) -> RedirectResponse:
        return RedirectResponse(f"/sign-in?error={reason}", status_code=status.HTTP_303_SEE_OTHER)

    @router.get(
        "/auth/google/start",
        operation_id="startGoogleSignIn",
        summary="Sends the browser to Google to sign in",
        status_code=status.HTTP_302_FOUND,
        response_class=RedirectResponse,
        responses={302: {"description": "To Google's sign-in page"}, 503: {"description": "Sign-in with Google is not configured"}},
    )
    async def start(request: Request) -> Any:
        if oauth is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sign-in with Google is not configured")
        redirect_uri = f"{settings.public_url}/api/v1/auth/google/callback"
        return await oauth.google.authorize_redirect(request, redirect_uri)

    @router.get(
        "/auth/google/callback",
        operation_id="finishGoogleSignIn",
        summary="Where Google sends the browser back after sign-in",
        status_code=status.HTTP_303_SEE_OTHER,
        response_class=RedirectResponse,
        responses={303: {"description": "To the home page, or to the sign-in page with the reason it failed"}},
    )
    async def callback(request: Request, db: Db) -> Any:
        if oauth is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sign-in with Google is not configured")
        try:
            token = await oauth.google.authorize_access_token(request)
        except OAuthError, JoseError:
            # A wrong state, nonce, audience, issuer, signature or expiry, or Google refusing the code.
            return refused("failed")
        claims = token.get("userinfo") or {}
        now = utc_now()
        try:
            learner = identity.sign_in_with_google(
                db,
                subject=str(claims["sub"]),
                email=str(claims.get("email", "")),
                email_verified=claims.get("email_verified") is True,
                name=claims.get("name"),
                owner_email=settings.owner_email,
                now=now,
            )
        except identity.SignInRefused as refusal:
            return refused(refusal.reason.replace("_", "-"))
        session_token = identity.start_session(db, learner, request.headers.get("user-agent"), now)
        response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            SESSION_COOKIE,
            session_token,
            max_age=identity.SESSION_DAYS * 24 * 3600,
            httponly=True,
            secure=settings.cookies_secure,
            samesite="lax",
            path="/",
        )
        return response

    @router.get(
        "/me", operation_id="getMe", summary="The signed-in learner", response_model=Me, responses={401: {"description": "Not signed in"}}
    )
    def me(learner: SignedIn) -> Me:
        return Me(displayName=learner.display_name, role=learner.role)

    @router.post(
        "/auth/sign-out",
        operation_id="signOut",
        summary="Ends the sign-in session on this device",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    def sign_out(db: Db, franca_session: Annotated[str | None, Cookie()] = None) -> Response:
        if franca_session:
            identity.end_session(db, franca_session, utc_now())
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookies_secure, httponly=True, samesite="lax")
        return response

    @router.post(
        "/invitations",
        operation_id="createInvitation",
        summary="Invites a learner by e-mail address (owner only)",
        status_code=status.HTTP_201_CREATED,
        response_model=InvitationOut,
        responses={401: {"description": "Not signed in"}, 403: {"description": "Only the owner can invite learners"}},
    )
    def create_invitation(body: InvitationRequest, db: Db, learner: SignedIn) -> InvitationOut:
        try:
            return _invitation(identity.invite(db, learner, body.email, utc_now()))
        except identity.NotAllowed as error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    @router.get(
        "/invitations",
        operation_id="listInvitations",
        summary="The invitations, newest first (owner only)",
        response_model=InvitationList,
        responses={401: {"description": "Not signed in"}, 403: {"description": "Only the owner can see invitations"}},
    )
    def invitations(db: Db, learner: SignedIn) -> InvitationList:
        try:
            return InvitationList(invitations=[_invitation(i) for i in identity.list_invitations(db, learner, utc_now())])
        except identity.NotAllowed as error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return router


def google_oauth(settings: Settings, transport: Any = None) -> OAuth | None:
    """The Authlib client for Google, or None when no client ID and secret are configured."""
    if settings.google is None:
        return None
    oauth = OAuth()
    client_kwargs: dict[str, Any] = {"scope": "openid email profile", "code_challenge_method": "S256"}
    if transport is not None:
        client_kwargs["transport"] = transport
    oauth.register(
        "google",
        client_id=settings.google.client_id,
        client_secret=settings.google.client_secret,
        server_metadata_url=GOOGLE_DISCOVERY,
        client_kwargs=client_kwargs,
    )
    return oauth


def install(app: FastAPI, settings: Settings, engine: Engine, transport: Any = None) -> APIRouter:
    app.state.engine = engine
    return auth_router(settings, google_oauth(settings, transport))
