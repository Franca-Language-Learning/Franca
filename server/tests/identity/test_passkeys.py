"""Passkeys as a second way to sign in (story E02-001), checked with a software passkey device."""

from datetime import timedelta

import pytest
from identity_helpers import NOW, ORIGIN
from identity_helpers import sign_in as sign_in_with_google
from passkey_device import PasskeyDevice, b64url
from sqlalchemy import Connection, text

from franca import identity

RP = identity.relying_party(ORIGIN)


def owner(connection: Connection) -> identity.Learner:
    return sign_in_with_google(connection)


def add(connection: Connection, learner: identity.Learner, device: PasskeyDevice, label: str = "Phone") -> identity.Passkey:
    started = identity.passkey_registration_options(connection, learner, RP)
    return identity.add_passkey(
        connection, learner, device.register(started.options), challenge=started.challenge, rp=RP, label=label, now=NOW
    )


def sign_in(connection: Connection, device: PasskeyDevice, **answer: object) -> identity.Learner:
    started = identity.passkey_sign_in_options(RP)
    return identity.sign_in_with_passkey(connection, device.sign_in(started.options, **answer), challenge=started.challenge, rp=RP, now=NOW)  # type: ignore[arg-type]


def audit_events(connection: Connection) -> list[tuple[str, str | None]]:
    rows = connection.execute(text("SELECT event, detail ->> '$.method' FROM identity_audit_event ORDER BY audit_event_id"))
    return [(row[0], row[1]) for row in rows]


def test_the_relying_party_is_the_public_address() -> None:
    assert RP == identity.RelyingParty(rp_id="franca.example.ts.net", origin=ORIGIN)
    assert identity.relying_party("http://localhost:8080/").rp_id == "localhost"


def test_the_relying_party_is_written_as_the_browser_writes_the_origin() -> None:
    assert identity.relying_party("https://Franca.Example.ts.net:443/") == RP
    assert identity.relying_party("http://LOCALHOST:80") == identity.RelyingParty(rp_id="localhost", origin="http://localhost")


def test_registration_options_ask_for_a_passkey_on_the_device(connection: Connection) -> None:
    learner = owner(connection)
    options = identity.passkey_registration_options(connection, learner, RP).options

    assert options["rp"] == {"id": "franca.example.ts.net", "name": "Franca"}
    assert options["user"]["name"] == "Nik"
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["attestation"] == "none"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["excludeCredentials"] == []


def test_a_learner_adds_a_passkey(connection: Connection) -> None:
    learner = owner(connection)
    device = PasskeyDevice(ORIGIN)

    passkey = add(connection, learner, device)

    assert passkey.passkey_id == b64url(device.credential_id)
    assert passkey.label == "Phone"
    assert passkey.synced is True
    assert passkey.last_used_at is None
    assert identity.list_passkeys(connection, learner) == [passkey]
    assert audit_events(connection) == [("sign_in", "google"), ("passkey_added", None)]


def test_a_passkey_already_added_is_excluded_from_the_next_registration(connection: Connection) -> None:
    learner = owner(connection)
    device = PasskeyDevice(ORIGIN)
    add(connection, learner, device)

    options = identity.passkey_registration_options(connection, learner, RP).options

    assert [c["id"] for c in options["excludeCredentials"]] == [b64url(device.credential_id)]


@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param(lambda device, options: device.register({**options, "challenge": b64url(b"another challenge")}), id="challenge"),
        pytest.param(lambda device, options: device.register(options, origin="https://evil.example"), id="origin"),
        pytest.param(lambda device, options: device.register(options, rp_id="evil.example"), id="rp-id"),
        pytest.param(lambda device, options: {"id": "x"}, id="malformed"),
    ],
)
def test_a_registration_that_fails_the_checks_adds_nothing(connection: Connection, spoil) -> None:  # type: ignore[no-untyped-def]
    learner = owner(connection)
    started = identity.passkey_registration_options(connection, learner, RP)

    with pytest.raises(identity.PasskeyNotAccepted):
        identity.add_passkey(
            connection, learner, spoil(PasskeyDevice(ORIGIN), started.options), challenge=started.challenge, rp=RP, label=None, now=NOW
        )

    assert identity.list_passkeys(connection, learner) == []


def test_a_passkey_made_without_checking_the_person_is_refused(connection: Connection) -> None:
    # A passkey is a whole sign-in on its own, so the device has to check the person (fingerprint, face or PIN).
    learner = owner(connection)
    with pytest.raises(identity.PasskeyNotAccepted):
        add(connection, learner, PasskeyDevice(ORIGIN, user_verified=False))


def test_a_sign_in_without_checking_the_person_is_refused(connection: Connection) -> None:
    learner = owner(connection)
    device = PasskeyDevice(ORIGIN)
    add(connection, learner, device)
    device.flags &= ~0x04
    with pytest.raises(identity.PasskeyNotAccepted):
        sign_in(connection, device)


def test_the_same_passkey_cannot_be_added_twice(connection: Connection) -> None:
    learner = owner(connection)
    device = PasskeyDevice(ORIGIN)
    add(connection, learner, device)

    with pytest.raises(identity.PasskeyNotAccepted):
        add(connection, learner, device)


def test_a_learner_has_at_most_ten_passkeys(connection: Connection) -> None:
    learner = owner(connection)
    for n in range(identity.MAX_PASSKEYS):
        add(connection, learner, PasskeyDevice(ORIGIN), label=f"Device {n}")

    with pytest.raises(identity.NotAllowed):
        identity.passkey_registration_options(connection, learner, RP)


def test_a_label_is_trimmed_and_shortened(connection: Connection) -> None:
    learner = owner(connection)
    assert add(connection, learner, PasskeyDevice(ORIGIN), label="  " + "x" * 80 + " ").label == "x" * 60
    assert add(connection, learner, PasskeyDevice(ORIGIN), label="   ").label is None


def test_sign_in_options_let_the_device_offer_its_passkeys(connection: Connection) -> None:
    options = identity.passkey_sign_in_options(RP).options
    assert options["rpId"] == "franca.example.ts.net"
    assert options["allowCredentials"] == []
    assert options["userVerification"] == "required"


def test_a_learner_signs_in_with_a_passkey(connection: Connection) -> None:
    learner = owner(connection)
    device = PasskeyDevice(ORIGIN)
    add(connection, learner, device)

    assert sign_in(connection, device) == learner

    (passkey,) = identity.list_passkeys(connection, learner)
    assert passkey.last_used_at == "2026-12-01T09:00:00.000Z"
    count = connection.execute(text("SELECT sign_count FROM identity_passkey")).scalar_one()
    assert count == 1
    assert audit_events(connection) == [("sign_in", "google"), ("passkey_added", None), ("sign_in", "passkey")]


def test_a_passkey_that_was_not_added_is_refused_as_unknown(connection: Connection) -> None:
    owner(connection)
    with pytest.raises(identity.PasskeyUnknown):
        sign_in(connection, PasskeyDevice(ORIGIN))


def test_a_sign_in_answer_with_a_wrong_origin_is_refused(connection: Connection) -> None:
    learner = owner(connection)
    device = PasskeyDevice(ORIGIN)
    add(connection, learner, device)
    with pytest.raises(identity.PasskeyNotAccepted):
        sign_in(connection, device, origin="https://evil.example")


def test_a_sign_in_answer_for_another_account_is_refused(connection: Connection) -> None:
    learner = owner(connection)
    device = PasskeyDevice(ORIGIN)
    add(connection, learner, device)
    with pytest.raises(identity.PasskeyNotAccepted):
        sign_in(connection, device, user_handle=b"someone else")


def test_a_counter_that_goes_back_suggests_a_copied_key_and_is_refused(connection: Connection) -> None:
    learner = owner(connection)
    device = PasskeyDevice(ORIGIN)
    add(connection, learner, device)
    sign_in(connection, device, sign_count=5)

    with pytest.raises(identity.PasskeyNotAccepted):
        sign_in(connection, device, sign_count=3)


def test_a_disabled_learner_cannot_sign_in_with_a_passkey(connection: Connection) -> None:
    owner(connection)
    identity.invite(connection, owner(connection), "learner@example.org", NOW)
    learner = identity.sign_in_with_google(
        connection, subject="g-l", email="learner@example.org", email_verified=True, name="L", owner_email="owner@example.org", now=NOW
    )
    device = PasskeyDevice(ORIGIN)
    add(connection, learner, device)
    connection.execute(text("UPDATE identity_learner SET status = 'disabled' WHERE learner_id = :id"), {"id": learner.learner_id})

    with pytest.raises(identity.SignInRefused) as refused:
        sign_in(connection, device)
    assert refused.value.reason == "disabled"


def test_a_learner_removes_a_passkey(connection: Connection) -> None:
    learner = owner(connection)
    passkey = add(connection, learner, PasskeyDevice(ORIGIN))

    identity.remove_passkey(connection, learner, passkey.passkey_id, NOW + timedelta(days=1))

    assert identity.list_passkeys(connection, learner) == []
    assert audit_events(connection) == [("sign_in", "google"), ("passkey_added", None), ("passkey_removed", None)]


def test_a_learner_cannot_remove_someone_elses_passkey(connection: Connection) -> None:
    first = owner(connection)
    passkey = add(connection, first, PasskeyDevice(ORIGIN))
    identity.invite(connection, first, "learner@example.org", NOW)
    second = identity.sign_in_with_google(
        connection, subject="g-l", email="learner@example.org", email_verified=True, name="L", owner_email="owner@example.org", now=NOW
    )

    for passkey_id in (passkey.passkey_id, "not-base64url!", b64url(b"unknown")):
        with pytest.raises(LookupError):
            identity.remove_passkey(connection, second, passkey_id, NOW)
    assert len(identity.list_passkeys(connection, first)) == 1
