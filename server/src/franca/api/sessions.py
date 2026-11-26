"""Routes for the signed-in learner's devices (story E02-003): the list, and signing out one or all other devices."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from franca import identity
from franca.api.auth import Db, SignedIn, session_token
from franca.platform import utc_now


class SessionOut(BaseModel):
    id: int
    deviceKind: str = Field(description="desktop, tablet or phone")
    browser: str = Field(description="The browser and system, such as Chrome on Windows")
    signedInAt: str
    lastUsedAt: str
    current: bool = Field(description="True for the device that sent this request")


class SessionList(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sessions": [
                        {
                            "id": 12,
                            "deviceKind": "desktop",
                            "browser": "Chrome on Windows",
                            "signedInAt": "2026-12-01T09:00:00.000Z",
                            "lastUsedAt": "2026-12-03T18:20:00.000Z",
                            "current": True,
                        },
                        {
                            "id": 9,
                            "deviceKind": "phone",
                            "browser": "Safari on iPhone",
                            "signedInAt": "2026-11-28T07:45:00.000Z",
                            "lastUsedAt": "2026-12-02T07:50:00.000Z",
                            "current": False,
                        },
                    ]
                }
            ]
        }
    )

    sessions: list[SessionOut]


class SignedOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"signedOut": 2}]})

    signedOut: int = Field(description="How many devices were signed out")


def session_router() -> APIRouter:
    router = APIRouter(tags=["identity"])
    unauthorised: dict[int | str, dict[str, Any]] = {401: {"description": "Not signed in"}}

    @router.get(
        "/sessions",
        operation_id="listSessions",
        summary="The devices the learner is signed in on",
        response_model=SessionList,
        responses=unauthorised,
    )
    def sessions(request: Request, db: Db, learner: SignedIn) -> SessionList:
        found = identity.list_sessions(db, learner, current_token=session_token(request), now=utc_now())
        return SessionList(
            sessions=[
                SessionOut(
                    id=s.session_id,
                    deviceKind=s.device_kind,
                    browser=s.browser,
                    signedInAt=s.created_at,
                    lastUsedAt=s.last_seen_at,
                    current=s.current,
                )
                for s in found
            ]
        )

    @router.delete(
        "/sessions/{sessionId}",
        operation_id="signOutDevice",
        summary="Signs out one of the learner's devices",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        responses={**unauthorised, 404: {"description": "The learner has no open session with this id"}},
    )
    def sign_out_device(sessionId: int, db: Db, learner: SignedIn) -> Response:  # noqa: N803 - the name in the URL
        try:
            identity.end_learner_session(db, learner, sessionId, utc_now())
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session") from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/sessions/sign-out-others",
        operation_id="signOutOtherDevices",
        summary="Signs out every device of the learner except this one",
        response_model=SignedOut,
        responses=unauthorised,
    )
    def sign_out_others(request: Request, db: Db, learner: SignedIn) -> SignedOut:
        # SignedIn has checked that the request has a valid session token.
        return SignedOut(signedOut=identity.end_other_sessions(db, learner, current_token=session_token(request) or "", now=utc_now()))

    return router
