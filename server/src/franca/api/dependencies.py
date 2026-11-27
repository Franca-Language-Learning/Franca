"""Request dependencies that the route modules share: the database connection of a request, the session cookie, the
signed-in learner, and the description of the answer for someone who is not signed in.

The engine and the settings are put in app.state by create_app, and are read from there by these functions.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import Connection, Engine

from franca import identity
from franca.platform import Settings, iso, utc_now

API_PREFIX = "/api/v1"
SESSION_COOKIE = "franca_session"
# Over https the cookie names start with __Host-, so the browser accepts them only from this host, over https, for
# the whole site. Other computers in the same tailnet share the site (tailXXXX.ts.net) and could otherwise set them.
SECURE_PREFIX = "__Host-"
RECENT_SIGN_IN = timedelta(minutes=15)
# The 401 answer in the API description of a route that needs a signed-in learner.
NOT_SIGNED_IN: dict[int | str, dict[str, Any]] = {401: {"description": "Not signed in"}}


def cookie_name(name: str, secure: bool) -> str:
    """The cookie's name as the browser keeps it: with the __Host- prefix over https."""
    return SECURE_PREFIX + name if secure else name


def engine_of(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def connection(request: Request) -> Iterator[Connection]:
    with engine_of(request).begin() as conn:
        yield conn


# scope="function": the transaction is committed before the response is sent, so a browser that follows a
# redirect at once finds the new session.
Db = Annotated[Connection, Depends(connection, scope="function")]


def session_cookie_name(settings: Settings) -> str:
    return cookie_name(SESSION_COOKIE, settings.cookies_secure)


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


SignedIn = Annotated[identity.Learner, Depends(current_learner)]
RecentlySignedIn = Annotated[identity.Learner, Depends(recently_signed_in)]
