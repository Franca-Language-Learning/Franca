"""A learner's sign-in sessions: the list of devices, signing out one or all others, and the sessions that end when a
passkey is removed (story E02-003)."""

from datetime import timedelta

import pytest
from identity_helpers import NOW, ORIGIN, sign_in
from passkey_device import PasskeyDevice
from sqlalchemy import Connection

from franca import identity

RP = identity.relying_party(ORIGIN)
PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
LAPTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0"


def test_the_list_has_the_open_sessions_newest_use_first_and_marks_this_one(connection: Connection) -> None:
    me = sign_in(connection)
    laptop = identity.start_session(connection, me, LAPTOP, NOW)
    phone = identity.start_session(connection, me, PHONE, NOW + timedelta(hours=2))
    ended = identity.start_session(connection, me, LAPTOP, NOW)
    identity.end_session(connection, ended, NOW)

    sessions = identity.list_sessions(connection, me, current_token=laptop, now=NOW + timedelta(hours=3))

    assert [(s.device_kind, s.current) for s in sessions] == [("phone", False), ("desktop", True)]
    assert sessions[0].browser == "Safari on iPhone"
    assert sessions[1].browser == "Chrome on Windows"
    assert identity.learner_for_session(connection, phone, NOW + timedelta(hours=3)) is not None


def test_another_learners_sessions_are_not_listed(connection: Connection) -> None:
    me = sign_in(connection)
    identity.invite(connection, me, "other@example.org", NOW)
    other = sign_in(connection, "g-other", "other@example.org")
    identity.start_session(connection, other, LAPTOP, NOW)
    assert identity.list_sessions(connection, me, current_token=None, now=NOW) == []


def test_a_learner_signs_out_one_of_their_devices(connection: Connection) -> None:
    me = sign_in(connection)
    current = identity.start_session(connection, me, LAPTOP, NOW)
    phone = identity.start_session(connection, me, PHONE, NOW)
    phone_id = next(s.session_id for s in identity.list_sessions(connection, me, current_token=current, now=NOW) if not s.current)

    identity.end_learner_session(connection, me, phone_id, NOW)

    assert identity.learner_for_session(connection, phone, NOW) is None
    assert identity.learner_for_session(connection, current, NOW) is not None
    with pytest.raises(LookupError):
        identity.end_learner_session(connection, me, phone_id, NOW)


def test_a_learner_cannot_sign_out_someone_elses_device(connection: Connection) -> None:
    me = sign_in(connection)
    identity.invite(connection, me, "other@example.org", NOW)
    other = sign_in(connection, "g-other", "other@example.org")
    token = identity.start_session(connection, other, LAPTOP, NOW)
    other_id = identity.list_sessions(connection, other, current_token=token, now=NOW)[0].session_id

    with pytest.raises(LookupError):
        identity.end_learner_session(connection, me, other_id, NOW)
    assert identity.learner_for_session(connection, token, NOW) is not None


def test_a_learner_signs_out_on_all_other_devices(connection: Connection) -> None:
    me = sign_in(connection)
    current = identity.start_session(connection, me, LAPTOP, NOW)
    others = [identity.start_session(connection, me, PHONE, NOW) for _ in range(2)]

    assert identity.end_other_sessions(connection, me, current_token=current, now=NOW) == 2

    assert identity.learner_for_session(connection, current, NOW) is not None
    assert all(identity.learner_for_session(connection, token, NOW) is None for token in others)


def test_removing_a_passkey_ends_the_sessions_started_with_it(connection: Connection) -> None:
    me = sign_in(connection)
    google_session = identity.start_session(connection, me, LAPTOP, NOW)
    device = PasskeyDevice(ORIGIN)
    started = identity.passkey_registration_options(connection, me, RP)
    passkey = identity.add_passkey(
        connection, me, device.register(started.options), challenge=started.challenge, rp=RP, label=None, now=NOW
    )
    options = identity.passkey_sign_in_options(RP)
    answer = device.sign_in(options.options)
    identity.sign_in_with_passkey(connection, answer, challenge=options.challenge, rp=RP, now=NOW)
    passkey_session = identity.start_session(connection, me, PHONE, NOW, passkey_id=answer["rawId"])

    identity.remove_passkey(connection, me, passkey.passkey_id, NOW)

    assert identity.learner_for_session(connection, passkey_session, NOW) is None
    assert identity.learner_for_session(connection, google_session, NOW) is not None
