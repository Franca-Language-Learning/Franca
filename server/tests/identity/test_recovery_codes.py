"""Recovery codes: ten single-use codes for signing in when the phone with the passkey is lost (story E02-002)."""

from datetime import timedelta

import pytest
from identity_helpers import NOW, OWNER_EMAIL, sign_in
from sqlalchemy import Connection, text

from franca import identity
from franca.identity import recovery

EMAIL = OWNER_EMAIL


def owner(connection: Connection) -> identity.Learner:
    return sign_in(connection)


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


class CountingHasher:
    """Counts the Argon2id checks, so the tests can see that each try does the same work."""

    def __init__(self, real: object) -> None:
        self.real = real
        self.checks = 0

    def verify(self, hash_: str, password: str) -> bool:
        self.checks += 1
        return self.real.verify(hash_, password)  # type: ignore[attr-defined, no-any-return]

    def hash(self, password: str) -> str:
        return self.real.hash(password)  # type: ignore[attr-defined, no-any-return]


@pytest.mark.parametrize("case", ["unknown address", "no codes", "right code", "wrong code"])
def test_each_try_does_the_same_work_so_the_time_does_not_tell_whether_an_address_is_known(
    connection: Connection, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    learner = owner(connection)
    codes = [] if case == "no codes" else identity.replace_recovery_codes(connection, learner, NOW)
    counter = CountingHasher(recovery.HASHER)
    monkeypatch.setattr(recovery, "HASHER", counter)
    email = "nobody@example.org" if case == "unknown address" else EMAIL
    code = codes[0] if case == "right code" else "AAAAA-AAAAA"

    try:
        identity.sign_in_with_recovery_code(connection, email, code, NOW)
    except identity.RecoveryCodeNotAccepted:
        pass

    assert counter.checks == identity.CODE_COUNT


def test_when_two_accounts_have_the_same_address_the_active_one_is_used(connection: Connection) -> None:
    first = owner(connection)
    identity.invite(connection, first, "shared@example.org", NOW)
    old = identity.sign_in_with_google(
        connection, subject="g-old", email="shared@example.org", email_verified=True, name="Old", owner_email=EMAIL, now=NOW
    )
    connection.execute(text("UPDATE identity_learner SET status = 'disabled' WHERE learner_id = :id"), {"id": old.learner_id})
    identity.invite(connection, first, "shared@example.org", NOW)
    new = identity.sign_in_with_google(
        connection, subject="g-new", email="Shared@example.org", email_verified=True, name="New", owner_email=EMAIL, now=NOW
    )
    code = identity.replace_recovery_codes(connection, new, NOW)[0]

    assert identity.sign_in_with_recovery_code(connection, "shared@example.org", code, NOW) == new
