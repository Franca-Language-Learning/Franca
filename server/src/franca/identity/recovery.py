"""Recovery codes (story E02-002): ten codes that each sign the learner in once, for when the phone with the passkey or
the Google account cannot be used.

The codes are shown once, when they are made. Only Argon2id hashes are stored. Making new codes removes the old
ones. A learner signs in with their e-mail address and a code. After five wrong codes in 15 minutes, further tries
for that learner are refused until 15 minutes have passed since the first of them.

A sign-in has three steps, so that the slow Argon2id checks run while no database transaction is open (SQLite has
one writer at a time, and every request would wait for it):
1. find_recovery_codes() reads the learner and their unused codes in a short transaction;
2. match_recovery_code() checks the typed code with no transaction open;
3. finish_recovery_sign_in() records the result in a second short transaction.
Each try checks the same number of hashes, whether the address is known or not and wherever the code is in the
list, so the time taken does not tell whether an address has an account.
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import Connection, text

from franca.identity.accounts import Learner, SignInRefused, normalise_email, record_event
from franca.platform import iso

CODE_COUNT = 10
# Letters and digits without 0, O, 1, I and L, which are easy to mix up: 31 characters, so ten of them give
# 49 bits per code.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10
MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
# The codes are random, so a lighter Argon2id setting than for passwords is enough (OWASP's minimum: 19 MiB, two
# passes).
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
# Checked when the address is unknown, so that a wrong address takes as long as a wrong code.
_DUMMY_HASH = HASHER.hash("not-a-recovery-code")


@dataclass(frozen=True, slots=True)
class RecoveryCodeStatus:
    unused: int
    created_at: str | None


class RecoveryCodeNotAccepted(Exception):
    """The address or the code is wrong, or the code was used already. The reason is not told to the person."""


class TooManyAttempts(Exception):
    pass


def _clean(code: str) -> str:
    return "".join(code.split()).replace("-", "").upper()


def _new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:5]}-{raw[5:]}"


def replace_recovery_codes(connection: Connection, learner: Learner, now: datetime) -> list[str]:
    """Makes ten new codes, removes the old ones and returns the new ones. They cannot be shown again."""
    codes = [_new_code() for _ in range(CODE_COUNT)]
    connection.execute(text("DELETE FROM identity_recovery_code WHERE learner_id = :learner"), {"learner": learner.learner_id})
    connection.execute(
        text("INSERT INTO identity_recovery_code (learner_id, code_hash, created_at) VALUES (:learner, :hash, :now)"),
        [{"learner": learner.learner_id, "hash": HASHER.hash(_clean(code)), "now": iso(now)} for code in codes],
    )
    record_event(connection, learner.learner_id, "recovery_codes_replaced", now)
    return codes


def recovery_code_status(connection: Connection, learner: Learner) -> RecoveryCodeStatus:
    row = connection.execute(
        text(
            "SELECT count(*) FILTER (WHERE used_at IS NULL) AS unused, max(created_at) AS created_at "
            "FROM identity_recovery_code WHERE learner_id = :learner"
        ),
        {"learner": learner.learner_id},
    ).one()
    return RecoveryCodeStatus(unused=int(row.unused or 0), created_at=row.created_at)


@dataclass(frozen=True, slots=True)
class RecoveryCandidate:
    """The learner with the typed address and their unused codes, or nobody (learner is None)."""

    learner: Learner | None = None
    status: str = "active"
    codes: list[tuple[int, str]] = field(default_factory=list)  # (recovery_code_id, code_hash)


def _learner_by_email(connection: Connection, email: str) -> tuple[Learner, str] | None:
    """The learner whose Google address is this one. If several have it, an active one is chosen first."""
    wanted = normalise_email(email)
    rows = connection.execute(
        text(
            "SELECT e.email, l.learner_id, l.uuid, l.display_name, l.role, l.status FROM identity_external_identity e "
            "JOIN identity_learner l USING (learner_id) WHERE e.provider = 'google' "
            "ORDER BY l.status = 'active' DESC, e.last_used_at DESC"
        )
    )
    for row in rows:
        if normalise_email(row.email) == wanted:
            return Learner(row.learner_id, row.uuid, row.display_name, row.role), row.status
    return None


def _recent_failures(connection: Connection, learner_id: int, now: datetime) -> int:
    return int(
        connection.execute(
            text(
                "SELECT count(*) FROM identity_audit_event WHERE learner_id = :learner AND event = 'sign_in_failed' "
                "AND detail ->> '$.method' = 'recovery_code' AND at > :since"
            ),
            {"learner": learner_id, "since": iso(now - FAILURE_WINDOW)},
        ).scalar_one()
    )


def find_recovery_codes(connection: Connection, email: str, now: datetime) -> RecoveryCandidate:
    """Step 1. Raises TooManyAttempts after five wrong codes for this learner in 15 minutes."""
    found = _learner_by_email(connection, email)
    if found is None:
        return RecoveryCandidate()
    learner, status = found
    if _recent_failures(connection, learner.learner_id, now) >= MAX_FAILURES:
        raise TooManyAttempts()
    rows = connection.execute(
        text("SELECT recovery_code_id, code_hash FROM identity_recovery_code WHERE learner_id = :learner AND used_at IS NULL"),
        {"learner": learner.learner_id},
    )
    return RecoveryCandidate(learner, status, [(row.recovery_code_id, row.code_hash) for row in rows])


def match_recovery_code(candidate: RecoveryCandidate, code: str) -> int | None:
    """Step 2: the id of the code that matches, or None. CODE_COUNT hashes are checked every time."""
    cleaned = _clean(code)
    padded = candidate.codes[:CODE_COUNT] + [(-1, _DUMMY_HASH)] * (CODE_COUNT - len(candidate.codes[:CODE_COUNT]))
    match = None
    for code_id, code_hash in padded:
        try:
            if HASHER.verify(code_hash, cleaned) and code_id >= 0 and match is None:
                match = code_id
        except VerificationError, InvalidHashError:
            continue
    return match


def finish_recovery_sign_in(connection: Connection, candidate: RecoveryCandidate, match: int | None, now: datetime) -> Learner:
    """Step 3. Raises RecoveryCodeNotAccepted, TooManyAttempts or SignInRefused("disabled"). A wrong code is written
    to the audit log, so the caller commits the transaction also when this raises RecoveryCodeNotAccepted."""
    learner = candidate.learner
    if learner is None:
        raise RecoveryCodeNotAccepted()
    # Checked again: other tries may have been counted while the codes were being checked.
    if _recent_failures(connection, learner.learner_id, now) >= MAX_FAILURES:
        raise TooManyAttempts()
    if match is None:
        record_event(connection, learner.learner_id, "sign_in_failed", now, {"method": "recovery_code"})
        raise RecoveryCodeNotAccepted()
    if candidate.status != "active":
        raise SignInRefused("disabled")
    used = connection.execute(
        text("UPDATE identity_recovery_code SET used_at = :now WHERE recovery_code_id = :id AND used_at IS NULL"),
        {"now": iso(now), "id": match},
    ).rowcount
    if not used:
        raise RecoveryCodeNotAccepted()  # used by another sign-in in the meantime, or replaced by new codes
    record_event(connection, learner.learner_id, "recovery_code_used", now)
    record_event(connection, learner.learner_id, "sign_in", now, {"method": "recovery_code"})
    return learner


def sign_in_with_recovery_code(connection: Connection, email: str, code: str, now: datetime) -> Learner:
    """The three steps on one connection, for callers that do not mind holding the transaction (tests, scripts)."""
    candidate = find_recovery_codes(connection, email, now)
    return finish_recovery_sign_in(connection, candidate, match_recovery_code(candidate, code), now)
