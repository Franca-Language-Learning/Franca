"""Recovery codes: ten single-use codes for signing in when the phone with the passkey is lost (story E02-002)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, text

from franca import identity

NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
EMAIL = "owner@example.org"


def owner(connection: Connection) -> identity.Learner:
    return identity.sign_in_with_google(
        connection, subject="g-owner", email=EMAIL, email_verified=True, name="Nik", owner_email=EMAIL, now=NOW
    )


def events(connection: Connection) -> list[str]:
    return list(connection.execute(text("SELECT event FROM identity_audit_event ORDER BY audit_event_id")).scalars())


def test_ten_codes_are_made_and_only_their_hashes_are_stored(connection: Connection) -> None:
    learner = owner(connection)
    codes = identity.replace_recovery_codes(connection, learner, NOW)

    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(len(code) == 11 and code[5] == "-" for code in codes)
    hashes = list(connection.execute(text("SELECT code_hash FROM identity_recovery_code")).scalars())
    assert len(hashes) == 10
    assert all(h.startswith("$argon2id$") for h in hashes)
    assert not any(code.replace("-", "") in h for code in codes for h in hashes)
    assert identity.recovery_code_status(connection, learner) == identity.RecoveryCodeStatus(
        unused=10, created_at="2026-12-01T09:00:00.000Z"
    )
    assert events(connection)[-1] == "recovery_codes_replaced"


def test_a_learner_without_codes_has_none(connection: Connection) -> None:
    assert identity.recovery_code_status(connection, owner(connection)) == identity.RecoveryCodeStatus(unused=0, created_at=None)


def test_a_code_signs_the_learner_in_once(connection: Connection) -> None:
    learner = owner(connection)
    code = identity.replace_recovery_codes(connection, learner, NOW)[3]

    assert identity.sign_in_with_recovery_code(connection, EMAIL, code, NOW) == learner
    with pytest.raises(identity.RecoveryCodeNotAccepted):
        identity.sign_in_with_recovery_code(connection, EMAIL, code, NOW)

    assert identity.recovery_code_status(connection, learner).unused == 9
    assert "recovery_code_used" in events(connection)


@pytest.mark.parametrize("typed", ["{code}", "{lower}", " {plain} ", "{spaced}"])
def test_a_code_can_be_typed_without_the_dash_in_any_case(connection: Connection, typed: str) -> None:
    learner = owner(connection)
    code = identity.replace_recovery_codes(connection, learner, NOW)[0]
    plain = code.replace("-", "")
    entry = typed.format(code=code, lower=code.lower(), plain=plain, spaced=f"{plain[:5]} {plain[5:]}")
    assert identity.sign_in_with_recovery_code(connection, EMAIL.upper(), entry, NOW) == learner


def test_new_codes_replace_the_old_ones(connection: Connection) -> None:
    learner = owner(connection)
    old = identity.replace_recovery_codes(connection, learner, NOW)
    identity.replace_recovery_codes(connection, learner, NOW + timedelta(days=1))

    with pytest.raises(identity.RecoveryCodeNotAccepted):
        identity.sign_in_with_recovery_code(connection, EMAIL, old[0], NOW + timedelta(days=1))
    assert identity.recovery_code_status(connection, learner).unused == 10


@pytest.mark.parametrize("email", [EMAIL, "nobody@example.org"])
def test_a_wrong_code_or_address_is_refused_in_the_same_way(connection: Connection, email: str) -> None:
    identity.replace_recovery_codes(connection, owner(connection), NOW)
    with pytest.raises(identity.RecoveryCodeNotAccepted):
        identity.sign_in_with_recovery_code(connection, email, "AAAAA-AAAAA", NOW)


def test_five_wrong_codes_in_15_minutes_stop_further_tries_for_a_while(connection: Connection) -> None:
    learner = owner(connection)
    code = identity.replace_recovery_codes(connection, learner, NOW)[0]
    for minute in range(5):
        with pytest.raises(identity.RecoveryCodeNotAccepted):
            identity.sign_in_with_recovery_code(connection, EMAIL, "AAAAA-AAAAA", NOW + timedelta(minutes=minute))

    with pytest.raises(identity.TooManyAttempts):
        identity.sign_in_with_recovery_code(connection, EMAIL, code, NOW + timedelta(minutes=5))
    assert identity.sign_in_with_recovery_code(connection, EMAIL, code, NOW + timedelta(minutes=20)) == learner


def test_a_disabled_learner_cannot_use_a_code(connection: Connection) -> None:
    first = owner(connection)
    identity.invite(connection, first, "learner@example.org", NOW)
    learner = identity.sign_in_with_google(
        connection, subject="g-l", email="learner@example.org", email_verified=True, name="L", owner_email=EMAIL, now=NOW
    )
    code = identity.replace_recovery_codes(connection, learner, NOW)[0]
    connection.execute(text("UPDATE identity_learner SET status = 'disabled' WHERE learner_id = :id"), {"id": learner.learner_id})

    with pytest.raises(identity.SignInRefused) as refused:
        identity.sign_in_with_recovery_code(connection, "learner@example.org", code, NOW)
    assert refused.value.reason == "disabled"
