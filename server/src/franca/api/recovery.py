"""Routes for recovery codes (story E02-002): making new codes, how many are left, and signing in with one."""

import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine
from starlette.concurrency import run_in_threadpool

from franca import identity
from franca.api.auth import Db, Me, RecentlySignedIn, SignedIn, session_token, set_session_cookie
from franca.platform import Settings, utc_now

NOT_ACCEPTED = "recovery-code-not-accepted"
WINDOW_SECONDS = 15 * 60
# Wrong codes allowed from one computer in 15 minutes, whatever address they are for.
COMPUTER_TRIES = 10


class AttemptLimiter:
    """Counts wrong tries in memory, by computer and by address, over a sliding window. The count for an address is
    kept whether or not the address has an account, so a refusal does not tell which addresses are known. The
    database keeps its own count for each learner, which a restart does not clear."""

    def __init__(self, window_seconds: float) -> None:
        self.window = window_seconds
        self._tries: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: tuple[str, str], now: float) -> list[float]:
        recent = [t for t in self._tries.get(key, []) if t > now - self.window]
        if recent:
            self._tries[key] = recent
        else:
            self._tries.pop(key, None)
        return recent

    def allow(self, key: tuple[str, str], limit: int) -> bool:
        with self._lock:
            return len(self._recent(key, time.monotonic())) < limit

    def record(self, key: tuple[str, str]) -> None:
        """Counts a wrong try. Keys whose tries are all older than the window are removed here, so a stream of new
        addresses does not fill up memory."""
        now = time.monotonic()
        with self._lock:
            for old in [k for k, times in self._tries.items() if times[-1] <= now - self.window]:
                del self._tries[old]
            self._tries.setdefault(key, []).append(now)

    def __len__(self) -> int:
        """The number of computers and addresses with tries in memory."""
        with self._lock:
            return len(self._tries)


def require_json(request: Request) -> None:
    """A form or a beacon from another site cannot send JSON without the browser asking first (CORS), so a sign-in that
    is not sent as JSON is refused. This stops another site from signing the browser in to someone else's account."""
    if not request.headers.get("content-type", "").split(";")[0].strip().lower() == "application/json":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send the request as JSON")


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


def too_many() -> JSONResponse:
    return JSONResponse({"detail": "too-many-attempts"}, status_code=status.HTTP_429_TOO_MANY_REQUESTS, headers={"Retry-After": "900"})


def recovery_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["identity"])
    limiter = AttemptLimiter(WINDOW_SECONDS)
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
            415: {"description": "The request was not sent as JSON"},
            429: {"description": "Too many wrong codes for this address, or too many tries from this computer, in 15 minutes"},
        },
        dependencies=[Depends(require_json)],
    )
    async def sign_in(body: RecoverySignIn, request: Request) -> Response:
        earlier = session_token(request)
        engine: Engine = request.app.state.engine
        address = identity.normalise_email(body.email)
        computer = request.client.host if request.client else "unknown"
        if not limiter.allow(("computer", computer), COMPUTER_TRIES) or not limiter.allow(("address", address), identity.MAX_FAILURES):
            return too_many()

        def find() -> identity.RecoveryCandidate:
            with engine.begin() as connection:
                return identity.find_recovery_codes(connection, body.email, utc_now())

        def finish(candidate: identity.RecoveryCandidate, match: int | None) -> tuple[identity.Learner, str] | None:
            with engine.begin() as connection:
                now = utc_now()
                try:
                    learner = identity.finish_recovery_sign_in(connection, candidate, match, now)
                except identity.RecoveryCodeNotAccepted:
                    return None  # returned, not raised, so the transaction is committed and the wrong code is counted
                if earlier:
                    identity.end_session(connection, earlier, now)  # an earlier session in this browser is closed
                return learner, identity.start_session(connection, learner, request.headers.get("user-agent"), now)

        try:
            candidate = await run_in_threadpool(find)
            # The Argon2id checks take a moment each, so they run in a worker thread with no transaction open.
            match = await run_in_threadpool(identity.match_recovery_code, candidate, body.code)
            signed_in = await run_in_threadpool(finish, candidate, match)
        except identity.TooManyAttempts:
            return too_many()
        except identity.SignInRefused as refusal:
            return JSONResponse({"detail": refusal.reason}, status_code=status.HTTP_401_UNAUTHORIZED)
        if signed_in is None:
            limiter.record(("computer", computer))
            limiter.record(("address", address))
            return JSONResponse({"detail": NOT_ACCEPTED}, status_code=status.HTTP_401_UNAUTHORIZED)
        learner, token = signed_in
        answer = JSONResponse(Me(displayName=learner.display_name, role=learner.role).model_dump())
        set_session_cookie(answer, settings, token)
        return answer

    return router
