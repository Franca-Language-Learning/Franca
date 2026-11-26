"""Routes for signing in with Google, the signed-in learner, signing out and invitations (story E02-001).

Sign-in with Google uses OpenID Connect with PKCE through Authlib. Authlib checks the state, the nonce and the
ID token's signature and expiry; the issuer and the audience are checked with the claims options below. The state of a sign-in in progress is kept in a short-lived signed
cookie (franca_oauth); the sign-in session is a random token in the session cookie, of which only a hash is
stored.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, Any

import httpx2
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from joserfc.errors import JoseError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.concurrency import run_in_threadpool

from franca import identity
from franca.platform import Settings, iso, utc_now

SESSION_COOKIE = "franca_session"
# Over https the cookie names start with __Host-, so the browser accepts them only from this host, over https, for
# the whole site. Other computers in the same tailnet share the site (tailXXXX.ts.net) and could otherwise set them.
SECURE_PREFIX = "__Host-"
PREVIOUS_SESSION_KEY = "previous_session"
RECENT_SIGN_IN = timedelta(minutes=15)
GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_DISCOVERY = f"{GOOGLE_ISSUER}/.well-known/openid-configuration"
# Errors from Google, the network, or the checks of the ID token. Each one ends the sign-in with error=failed.
SIGN_IN_ERRORS = (OAuthError, JoseError, httpx2.HTTPError, ValueError, KeyError)


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


# scope="function": the transaction is committed before the response is sent, so a browser that follows a
# redirect at once finds the new session.
Db = Annotated[Connection, Depends(connection, scope="function")]


def session_cookie_name(settings: Settings) -> str:
    return SECURE_PREFIX + SESSION_COOKIE if settings.cookies_secure else SESSION_COOKIE


def session_token(request: Request) -> str | None:
    """The session token in the request's cookie, if there is one."""
    return request.cookies.get(session_cookie_name(request.app.state.settings)) or None


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        session_cookie_name(settings),
        token,
        max_age=identity.SESSION_DAYS * 24 * 3600,
        httponly=True,
        secure=settings.cookies_secure,
        # Strict: the browser does not send the cookie with a request that another site starts.
        samesite="strict",
        path="/",
    )


def current_session(request: Request, response: Response, db: Db) -> identity.SessionCheck:
    token = session_token(request)
    check = identity.learner_for_session(db, token, utc_now()) if token else None
    if check is None or token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    if check.extended:
        # The session was extended in the database, so the cookie in the browser is extended to match.
        set_session_cookie(response, request.app.state.settings, token)
    return check


def current_learner(check: Annotated[identity.SessionCheck, Depends(current_session)]) -> identity.Learner:
    return check.learner


def recently_signed_in(check: Annotated[identity.SessionCheck, Depends(current_session)]) -> identity.Learner:
    """The learner, if they signed in within the last RECENT_SIGN_IN. Steps that add a way in need this, so that
    someone with a stolen session cookie cannot add one."""
    if check.signed_in_at < iso(utc_now() - RECENT_SIGN_IN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "sign-in-again")
    return check.learner


def _session_id_of(request: Request, token: str) -> int | None:
    engine: Engine = request.app.state.engine
    with engine.begin() as connection:
        return identity.session_id_for_token(connection, token, utc_now())


SignedIn = Annotated[identity.Learner, Depends(current_learner)]
RecentlySignedIn = Annotated[identity.Learner, Depends(recently_signed_in)]


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
        # Google sends the browser back from another site, so the Strict session cookie is not sent to the callback.
        # The session that is open now is noted here, where the cookie is sent, and the callback ends it.
        token = session_token(request)
        if token:
            request.session[PREVIOUS_SESSION_KEY] = await run_in_threadpool(_session_id_of, request, token)
        try:
            return await oauth.google.authorize_redirect(request, redirect_uri)
        except SIGN_IN_ERRORS:
            return refused("failed")

    @router.get(
        "/auth/google/callback",
        operation_id="finishGoogleSignIn",
        summary="Where Google sends the browser back after sign-in",
        status_code=status.HTTP_303_SEE_OTHER,
        response_class=RedirectResponse,
        responses={303: {"description": "To the home page, or to the sign-in page with the reason it failed"}},
    )
    async def callback(request: Request, db: Db) -> Any:
        if oauth is None or settings.google is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sign-in with Google is not configured")
        claims_options = {
            "iss": {"essential": True, "values": [GOOGLE_ISSUER]},
            "aud": {"essential": True, "value": settings.google.client_id},
        }
        try:
            token = await oauth.google.authorize_access_token(request, claims_options=claims_options)
            claims = token["userinfo"]
            subject = str(claims["sub"])
        except SIGN_IN_ERRORS:
            # A wrong state, nonce, audience, issuer, signature or expiry, Google refusing the code, or Google or
            # the network failing.
            return refused("failed")

        def finish() -> str:
            # Database work, run in a worker thread so that a wait for the database does not hold up other requests.
            now = utc_now()
            learner = identity.sign_in_with_google(
                db,
                subject=subject,
                email=str(claims.get("email", "")),
                email_verified=claims.get("email_verified") is True,
                name=claims.get("name"),
                owner_email=settings.owner_email,
                now=now,
            )
            previous = request.session.pop(PREVIOUS_SESSION_KEY, None)
            if isinstance(previous, int):
                identity.end_session_by_id(db, previous, now)  # the earlier session in this browser is closed
            return identity.start_session(db, learner, request.headers.get("user-agent"), now)

        try:
            new_token = await run_in_threadpool(finish)
        except identity.SignInRefused as refusal:
            return refused(refusal.reason.replace("_", "-"))
        except IntegrityError, OperationalError:
            # For example two first sign-ins of the owner at the same moment: the second one is refused.
            return refused("failed")
        response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        set_session_cookie(response, settings, new_token)
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
    def sign_out(request: Request, db: Db) -> Response:
        token = session_token(request)
        if token:
            identity.end_session(db, token, utc_now())
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(session_cookie_name(settings), path="/", secure=settings.cookies_secure, httponly=True, samesite="strict")
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
    app.state.settings = settings
    return auth_router(settings, google_oauth(settings, transport))
