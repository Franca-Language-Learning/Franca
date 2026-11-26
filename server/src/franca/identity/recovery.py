"""Recovery codes (story E02-002): ten codes that each sign the learner in once, for when the phone with the passkey or
the Google account cannot be used.

The codes are shown once, when they are made. Only Argon2id hashes are stored. Making new codes removes the old
ones. A learner signs in with their e-mail address and a code. After five wrong codes in 15 minutes, further tries
for that learner are refused until 15 minutes have passed since the first of them.
"""

import secrets
from dataclasses import dataclass
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


def _learner_by_email(connection: Connection, email: str) -> tuple[Learner, str] | None:
    wanted = normalise_email(email)
    rows = connection.execute(
        text(
            "SELECT e.email, l.learner_id, l.uuid, l.display_name, l.role, l.status FROM identity_external_identity e "
            "JOIN identity_learner l USING (learner_id) WHERE e.provider = 'google'"
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


def sign_in_with_recovery_code(connection: Connection, email: str, code: str, now: datetime) -> Learner:
    """Raises RecoveryCodeNotAccepted, TooManyAttempts or SignInRefused("disabled"). A wrong code is written to the
    audit log, so the caller commits the transaction also when this raises RecoveryCodeNotAccepted."""
    cleaned = _clean(code)
    found = _learner_by_email(connection, email)
    if found is None:
        try:
            HASHER.verify(_DUMMY_HASH, cleaned)
        except VerificationError:
            pass
        raise RecoveryCodeNotAccepted()
    learner, status = found
    if _recent_failures(connection, learner.learner_id, now) >= MAX_FAILURES:
        raise TooManyAttempts()

    rows = connection.execute(
        text("SELECT recovery_code_id, code_hash FROM identity_recovery_code WHERE learner_id = :learner AND used_at IS NULL"),
        {"learner": learner.learner_id},
    ).all()
    match = None
    for row in rows:
        try:
            HASHER.verify(row.code_hash, cleaned)
            match = row.recovery_code_id
            break
        except VerificationError, InvalidHashError:
            continue
    if match is None:
        record_event(connection, learner.learner_id, "sign_in_failed", now, {"method": "recovery_code"})
        raise RecoveryCodeNotAccepted()
    if status != "active":
        raise SignInRefused("disabled")

    used = connection.execute(
        text("UPDATE identity_recovery_code SET used_at = :now WHERE recovery_code_id = :id AND used_at IS NULL"),
        {"now": iso(now), "id": match},
    ).rowcount
    if not used:
        raise RecoveryCodeNotAccepted()  # used by another sign-in at the same moment
    record_event(connection, learner.learner_id, "recovery_code_used", now)
    record_event(connection, learner.learner_id, "sign_in", now, {"method": "recovery_code"})
    return learner
