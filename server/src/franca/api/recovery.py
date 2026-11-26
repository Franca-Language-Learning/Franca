"""Routes for recovery codes (story E02-002): making new codes, how many are left, and signing in with one."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from franca import identity
from franca.api.auth import Db, Me, RecentlySignedIn, SignedIn, set_session_cookie
from franca.platform import Settings, utc_now

NOT_ACCEPTED = "recovery-code-not-accepted"


class RecoveryCodeStatusOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"unused": 9, "createdAt": "2026-12-01T09:00:00.000Z"}]})

    unused: int = Field(description="Codes that have not been used yet")
    createdAt: str | None = Field(description="When the codes were made, or null when the learner has none")


class RecoveryCodes(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "codes": [
                        "ABCDE-FGHJK",
                        "MNPQR-STUVW",
                        "XYZ23-45678",
                        "9ABCD-EFGHJ",
                        "KMNPQ-RSTUV",
                        "WXYZ2-34567",
                        "89ABC-DEFGH",
                        "JKMNP-QRSTU",
                        "VWXYZ-23456",
                        "789AB-CDEFG",
                    ]
                }
            ]
        }
    )

    codes: list[str] = Field(description="The new codes. They are shown this once and cannot be shown again.")


class RecoverySignIn(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=40)


def recovery_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["identity"])
    unauthorised: dict[int | str, dict[str, str]] = {401: {"description": "Not signed in"}}

    @router.get(
        "/recovery-codes",
        operation_id="getRecoveryCodeStatus",
        summary="How many of the signed-in learner's recovery codes are left",
        response_model=RecoveryCodeStatusOut,
        responses=unauthorised,
    )
    def code_status(db: Db, learner: SignedIn) -> RecoveryCodeStatusOut:
        found = identity.recovery_code_status(db, learner)
        return RecoveryCodeStatusOut(unused=found.unused, createdAt=found.created_at)

    @router.post(
        "/recovery-codes",
        operation_id="makeRecoveryCodes",
        summary="Makes ten new recovery codes; the old ones stop working",
        status_code=status.HTTP_201_CREATED,
        response_model=RecoveryCodes,
        responses={**unauthorised, 403: {"description": "The learner signed in more than 15 minutes ago (sign-in-again)"}},
    )
    def make_codes(response: Response, db: Db, learner: RecentlySignedIn) -> RecoveryCodes:
        response.headers["Cache-Control"] = "no-store"
        return RecoveryCodes(codes=identity.replace_recovery_codes(db, learner, utc_now()))

    @router.post(
        "/auth/recovery-code",
        operation_id="signInWithRecoveryCode",
        summary="Signs in with an e-mail address and a recovery code",
        response_model=Me,
        responses={
            401: {"description": "The address or the code is wrong, the code was used already, or the account is disabled"},
            429: {"description": "Five wrong codes in 15 minutes; try again later"},
        },
    )
    async def sign_in(body: RecoverySignIn, request: Request, db: Db, franca_session: Annotated[str | None, Cookie()] = None) -> Response:
        # A refusal is answered with a response and not raised, so the transaction is committed and the wrong code
        # is counted.
        def finish() -> identity.Learner:
            return identity.sign_in_with_recovery_code(db, body.email, body.code, utc_now())

        try:
            # Argon2id checks take a moment each, so they run in a worker thread.
            learner = await run_in_threadpool(finish)
        except identity.RecoveryCodeNotAccepted:
            return JSONResponse({"detail": NOT_ACCEPTED}, status_code=status.HTTP_401_UNAUTHORIZED)
        except identity.TooManyAttempts:
            return JSONResponse(
                {"detail": "too-many-attempts"}, status_code=status.HTTP_429_TOO_MANY_REQUESTS, headers={"Retry-After": "900"}
            )
        except identity.SignInRefused as refusal:
            return JSONResponse({"detail": refusal.reason}, status_code=status.HTTP_401_UNAUTHORIZED)

        def start() -> str:
            now = utc_now()
            if franca_session:
                identity.end_session(db, franca_session, now)  # an earlier session in this browser is closed
            return identity.start_session(db, learner, request.headers.get("user-agent"), now)

        token = await run_in_threadpool(start)
        answer = JSONResponse(Me(displayName=learner.display_name, role=learner.role).model_dump())
        set_session_cookie(answer, settings, token)
        return answer

    return router
