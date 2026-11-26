"""Accounts, Google sign-in, invitations and sessions (story E02-001)."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, text

from franca import identity

NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
OWNER = "owner@example.org"


def google(
    connection: Connection, subject: str, email: str, *, verified: bool = True, now: datetime = NOW, name: str | None = "A Person"
) -> identity.Learner:
    return identity.sign_in_with_google(
        connection, subject=subject, email=email, email_verified=verified, name=name, owner_email=OWNER, now=now
    )


def owner(connection: Connection) -> identity.Learner:
    return google(connection, "owner-sub", OWNER, name="Owner")


def test_the_owner_address_becomes_the_owner_on_first_sign_in(connection: Connection) -> None:
    learner = google(connection, "sub-1", "Owner@Example.org", name="Nik")
    assert learner.role == "owner"
    assert learner.display_name == "Nik"


def test_a_second_google_account_with_the_owner_address_is_refused_once_there_is_an_owner(connection: Connection) -> None:
    owner(connection)
    with pytest.raises(identity.SignInRefused) as refused:
        google(connection, "another-sub", OWNER)
    assert refused.value.reason == "not_invited"


def test_an_unverified_address_is_refused(connection: Connection) -> None:
    with pytest.raises(identity.SignInRefused) as refused:
        google(connection, "sub-1", OWNER, verified=False)
    assert refused.value.reason == "email_not_verified"


def test_a_stranger_is_refused(connection: Connection) -> None:
    with pytest.raises(identity.SignInRefused) as refused:
        google(connection, "sub-x", "stranger@example.org")
    assert refused.value.reason == "not_invited"
    assert connection.execute(text("SELECT count(*) FROM identity_learner")).scalar() == 0


def test_an_invited_address_gets_a_learner_account_and_the_invitation_is_used(connection: Connection) -> None:
    identity.invite(connection, owner(connection), " Partner@Example.org ", NOW)
    learner = google(connection, "partner-sub", "partner@example.org", now=NOW + timedelta(days=1))
    assert learner.role == "learner"
    statuses = [i.status for i in identity.list_invitations(connection, owner(connection), NOW + timedelta(days=1))]
    assert statuses == ["accepted"]
    with pytest.raises(identity.SignInRefused):
        google(connection, "someone-else", "partner@example.org", now=NOW + timedelta(days=1))


def test_an_invitation_expires_after_14_days(connection: Connection) -> None:
    identity.invite(connection, owner(connection), "late@example.org", NOW)
    with pytest.raises(identity.SignInRefused):
        google(connection, "late-sub", "late@example.org", now=NOW + timedelta(days=14, seconds=1))


def test_a_new_invitation_replaces_an_open_one(connection: Connection) -> None:
    the_owner = owner(connection)
    identity.invite(connection, the_owner, "a@example.org", NOW)
    identity.invite(connection, the_owner, "a@example.org", NOW + timedelta(days=1))
    assert [i.status for i in identity.list_invitations(connection, the_owner, NOW + timedelta(days=1))] == ["open", "withdrawn"]


def test_only_the_owner_can_invite_or_see_invitations(connection: Connection) -> None:
    identity.invite(connection, owner(connection), "learner@example.org", NOW)
    learner = google(connection, "learner-sub", "learner@example.org")
    with pytest.raises(identity.NotAllowed):
        identity.invite(connection, learner, "friend@example.org", NOW)
    with pytest.raises(identity.NotAllowed):
        identity.list_invitations(connection, learner, NOW)


def test_a_returning_google_account_is_recognised_by_its_subject_even_with_a_new_address(connection: Connection) -> None:
    first = owner(connection)
    again = google(connection, "owner-sub", "new-address@example.org", now=NOW + timedelta(days=3))
    assert again == first


def test_a_disabled_learner_is_refused(connection: Connection) -> None:
    identity.invite(connection, owner(connection), "learner@example.org", NOW)
    learner = google(connection, "learner-sub", "learner@example.org")
    connection.execute(text("UPDATE identity_learner SET status = 'disabled' WHERE learner_id = :id"), {"id": learner.learner_id})
    with pytest.raises(identity.SignInRefused) as refused:
        google(connection, "learner-sub", "learner@example.org")
    assert refused.value.reason == "disabled"


def test_a_session_token_finds_its_learner_and_only_its_hash_is_stored(connection: Connection) -> None:
    learner = owner(connection)
    token = identity.start_session(connection, learner, "Mozilla/5.0 (iPhone) Mobile", NOW)
    assert identity.learner_for_session(connection, token, NOW + timedelta(minutes=5)) == identity.SessionCheck(learner, extended=False)
    stored = connection.execute(text("SELECT token_hash, device_kind FROM identity_auth_session")).one()
    assert stored.token_hash == hashlib.sha256(token.encode()).digest()
    assert stored.device_kind == "phone"


def test_a_session_ends_after_30_days_without_use_and_each_use_extends_it(connection: Connection) -> None:
    learner = owner(connection)
    token = identity.start_session(connection, learner, None, NOW)
    assert identity.learner_for_session(connection, token, NOW + timedelta(days=29)) == identity.SessionCheck(learner, extended=True)
    assert identity.learner_for_session(connection, token, NOW + timedelta(days=58)) == identity.SessionCheck(learner, extended=True)
    assert identity.learner_for_session(connection, token, NOW + timedelta(days=89)) is None


def test_a_session_is_written_at_most_once_an_hour(connection: Connection) -> None:
    learner = owner(connection)
    token = identity.start_session(connection, learner, None, NOW)
    assert identity.learner_for_session(connection, token, NOW + timedelta(minutes=59)).extended is False  # type: ignore[union-attr]
    assert identity.learner_for_session(connection, token, NOW + timedelta(minutes=61)).extended is True  # type: ignore[union-attr]


def test_addresses_are_compared_after_nfc_and_casefolding(connection: Connection) -> None:
    identity.invite(connection, owner(connection), "STRAẞE@example.org", NOW)
    learner = google(connection, "s-sub", "strasse@example.org")
    assert learner.role == "learner"


def test_a_signed_out_session_and_an_unknown_token_find_nobody(connection: Connection) -> None:
    token = identity.start_session(connection, owner(connection), None, NOW)
    identity.end_session(connection, token, NOW)
    assert identity.learner_for_session(connection, token, NOW) is None
    assert identity.learner_for_session(connection, "not-a-token", NOW) is None
