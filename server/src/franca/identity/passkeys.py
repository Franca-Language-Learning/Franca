"""Passkeys as a second way to sign in (story E02-001).

A signed-in learner can add a passkey: a key pair kept on their phone, laptop or password manager. After that they
can sign in with it without Google. py_webauthn (BSD-3-Clause) makes the options for the browser and checks the
browser's answers; this module stores the passkeys and decides who is signed in.

The passkeys are discoverable (the device keeps the account with the key), so a learner signs in without typing an
e-mail address first. The browser's answer names the passkey and the learner it was made for, and both are checked.
No attestation is asked for, because Franca does not limit which devices may be used. The device has to check the
person (fingerprint, face, PIN or screen lock), because a passkey is a whole sign-in on its own.
"""

import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Connection, text
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    CredentialDeviceType,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from franca.identity.accounts import Learner, NotAllowed, SignInRefused, record_event
from franca.platform import iso

RP_NAME = "Franca"
MAX_PASSKEYS = 10
LABEL_LENGTH = 60
# ES256, Ed25519 and RS256 cover the devices in use: phones, laptops, password managers and security keys.
ALGORITHMS = [COSEAlgorithmIdentifier.ECDSA_SHA_256, COSEAlgorithmIdentifier.EDDSA, COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256]
# Errors that a malformed or altered answer from the browser can cause while it is read and checked.
ANSWER_ERRORS = (WebAuthnException, ValueError, TypeError, KeyError, AttributeError, binascii.Error)


@dataclass(frozen=True, slots=True)
class RelyingParty:
    """The site that passkeys belong to: the host name of the address that learners use, and that address."""

    rp_id: str
    origin: str


@dataclass(frozen=True, slots=True)
class Passkey:
    passkey_id: str  # the credential id, base64url
    label: str | None
    created_at: str
    last_used_at: str | None
    synced: bool  # kept in a password manager or cloud account, so it is on more than one device


@dataclass(frozen=True, slots=True)
class PasskeyChallenge:
    """The options for the browser, and the challenge in them, which the server keeps until the answer comes."""

    options: dict[str, Any]
    challenge: bytes


class PasskeyNotAccepted(Exception):
    """The browser's answer failed a check, or names a passkey that Franca does not have."""


class PasskeyUnknown(PasskeyNotAccepted):
    """The answer names a passkey that Franca does not have, for example one the learner removed."""


DEFAULT_PORTS = {"https": 443, "http": 80}


def relying_party(public_url: str) -> RelyingParty:
    """The origin is written as the browser writes it: scheme and host in lower case, and no default port."""
    parts = urlsplit(public_url.strip().rstrip("/"))
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port != DEFAULT_PORTS.get(scheme) else ""
    return RelyingParty(rp_id=host, origin=f"{scheme}://{host}{port}")


def _user_handle(learner_uuid: str) -> bytes:
    # The learner's UUID as 16 bytes. It names no person, as the WebAuthn standard asks.
    return uuid.UUID(learner_uuid).bytes


def _label(label: str | None) -> str | None:
    cleaned = " ".join((label or "").split())[:LABEL_LENGTH]
    return cleaned or None


def _passkey(row: Any) -> Passkey:
    return Passkey(bytes_to_base64url(row.credential_id), row.label, row.created_at, row.last_used_at, bool(row.backed_up))


def list_passkeys(connection: Connection, learner: Learner) -> list[Passkey]:
    rows = connection.execute(
        text(
            "SELECT credential_id, label, created_at, last_used_at, backed_up FROM identity_passkey "
            "WHERE learner_id = :learner ORDER BY created_at, credential_id"
        ),
        {"learner": learner.learner_id},
    )
    return [_passkey(row) for row in rows]


def passkey_registration_options(connection: Connection, learner: Learner, rp: RelyingParty) -> PasskeyChallenge:
    existing = list(
        connection.execute(
            text("SELECT credential_id FROM identity_passkey WHERE learner_id = :learner"), {"learner": learner.learner_id}
        ).scalars()
    )
    if len(existing) >= MAX_PASSKEYS:
        raise NotAllowed(f"A learner can have up to {MAX_PASSKEYS} passkeys")
    options = generate_registration_options(
        rp_id=rp.rp_id,
        rp_name=RP_NAME,
        user_id=_user_handle(learner.uuid),
        user_name=learner.display_name,
        user_display_name=learner.display_name,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED
        ),
        # The browser does not make a second passkey on a device that already has one for this learner.
        exclude_credentials=[PublicKeyCredentialDescriptor(id=bytes(credential_id)) for credential_id in existing],
        supported_pub_key_algs=ALGORITHMS,
    )
    return PasskeyChallenge(json.loads(options_to_json(options)), options.challenge)


def add_passkey(
    connection: Connection,
    learner: Learner,
    answer: dict[str, Any],
    *,
    challenge: bytes,
    rp: RelyingParty,
    label: str | None,
    now: datetime,
) -> Passkey:
    try:
        verified = verify_registration_response(
            credential=answer,
            expected_challenge=challenge,
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            supported_pub_key_algs=ALGORITHMS,
            require_user_verification=True,
        )
        transports = answer.get("response", {}).get("transports") or []
        transports_text = ",".join(str(t) for t in transports)[:200] or None
    except ANSWER_ERRORS as error:
        raise PasskeyNotAccepted(str(error)) from error

    known = connection.execute(text("SELECT 1 FROM identity_passkey WHERE credential_id = :id"), {"id": verified.credential_id}).first()
    if known is not None:
        raise PasskeyNotAccepted("This passkey has been added already")
    count = connection.execute(
        text("SELECT count(*) FROM identity_passkey WHERE learner_id = :learner"), {"learner": learner.learner_id}
    ).scalar_one()
    if count >= MAX_PASSKEYS:
        raise NotAllowed(f"A learner can have up to {MAX_PASSKEYS} passkeys")

    backup_eligible = verified.credential_device_type == CredentialDeviceType.MULTI_DEVICE
    connection.execute(
        text(
            "INSERT INTO identity_passkey (credential_id, learner_id, public_key, sign_count, transports, aaguid, "
            "backup_eligible, backed_up, label, created_at) "
            "VALUES (:id, :learner, :key, :count, :transports, :aaguid, :eligible, :backed_up, :label, :now)"
        ),
        {
            "id": verified.credential_id,
            "learner": learner.learner_id,
            "key": verified.credential_public_key,
            "count": verified.sign_count,
            "transports": transports_text,
            "aaguid": uuid.UUID(verified.aaguid).bytes,
            "eligible": int(backup_eligible),
            "backed_up": int(verified.credential_backed_up),
            "label": _label(label),
            "now": iso(now),
        },
    )
    record_event(connection, learner.learner_id, "passkey_added", now)
    return Passkey(bytes_to_base64url(verified.credential_id), _label(label), iso(now), None, verified.credential_backed_up)


def passkey_sign_in_options(rp: RelyingParty) -> PasskeyChallenge:
    # No list of passkeys: the device offers the passkeys it has for this site, so the learner picks an account
    # on the device and does not type anything here.
    options = generate_authentication_options(rp_id=rp.rp_id, user_verification=UserVerificationRequirement.REQUIRED)
    return PasskeyChallenge(json.loads(options_to_json(options)), options.challenge)


def sign_in_with_passkey(connection: Connection, answer: dict[str, Any], *, challenge: bytes, rp: RelyingParty, now: datetime) -> Learner:
    try:
        credential_id = base64url_to_bytes(str(answer["rawId"]))
        user_handle = base64url_to_bytes(str(answer["response"]["userHandle"] or ""))
    except ANSWER_ERRORS as error:
        raise PasskeyNotAccepted("The answer from the browser could not be read") from error

    row = connection.execute(
        text(
            "SELECT p.public_key, p.sign_count, l.learner_id, l.uuid, l.display_name, l.role, l.status "
            "FROM identity_passkey p JOIN identity_learner l USING (learner_id) WHERE p.credential_id = :id"
        ),
        {"id": credential_id},
    ).one_or_none()
    if row is None:
        raise PasskeyUnknown("Franca does not have this passkey")
    if user_handle != _user_handle(row.uuid):
        raise PasskeyNotAccepted("The passkey was made for another account")
    try:
        verified = verify_authentication_response(
            credential=answer,
            expected_challenge=challenge,
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            credential_public_key=row.public_key,
            # A counter that does not go up can mean that the key was copied, and the sign-in is refused.
            credential_current_sign_count=row.sign_count,
            require_user_verification=True,
        )
    except ANSWER_ERRORS as error:
        raise PasskeyNotAccepted(str(error)) from error
    if row.status != "active":
        raise SignInRefused("disabled")

    updated = connection.execute(
        text(
            "UPDATE identity_passkey SET sign_count = :count, backed_up = :backed_up, last_used_at = :now "
            "WHERE credential_id = :id AND sign_count = :old"
        ),
        {
            "count": verified.new_sign_count,
            "backed_up": int(verified.credential_backed_up),
            "now": iso(now),
            "id": credential_id,
            "old": row.sign_count,
        },
    ).rowcount
    if not updated:
        # Another sign-in with this passkey changed the counter in the meantime.
        raise PasskeyNotAccepted("The passkey was used at the same moment by another sign-in")
    record_event(connection, row.learner_id, "sign_in", now, {"method": "passkey"})
    return Learner(row.learner_id, row.uuid, row.display_name, row.role)


def remove_passkey(connection: Connection, learner: Learner, passkey_id: str, now: datetime) -> None:
    """Raises LookupError when the learner has no passkey with this id."""
    try:
        credential_id = base64url_to_bytes(passkey_id)
    except ANSWER_ERRORS as error:
        raise LookupError("No such passkey") from error
    removed = connection.execute(
        text("DELETE FROM identity_passkey WHERE credential_id = :id AND learner_id = :learner"),
        {"id": credential_id, "learner": learner.learner_id},
    ).rowcount
    if not removed:
        raise LookupError("No such passkey")
    record_event(connection, learner.learner_id, "passkey_removed", now)
