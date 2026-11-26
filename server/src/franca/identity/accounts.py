"""Accounts, Google sign-in, invitations and sign-in sessions (story E02-001).

Franca stores no passwords. A person signs in with a Google account whose e-mail address Google has verified.
The first time, Franca makes an account for them if:
- their address is the owner address given at installation and there is no owner yet, or
- the owner has invited their address, and the invitation has not expired or been withdrawn.

After that, the Google account is recognised by its subject id, which stays the same if the address changes.
"""

import hashlib
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, text

from franca.platform import iso

SESSION_DAYS = 30
INVITATION_DAYS = 14


@dataclass(frozen=True, slots=True)
class Learner:
    learner_id: int
    uuid: str
    display_name: str
    role: str


@dataclass(frozen=True, slots=True)
class Invitation:
    email: str
    created_at: str
    expires_at: str
    status: str


class SignInRefused(Exception):
    """Reasons: email_not_verified, not_invited, disabled."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class NotAllowed(Exception):
    pass


def normalise_email(email: str) -> str:
    return email.strip().lower()


def _learner(row: Sequence[Any]) -> Learner:
    return Learner(int(row[0]), str(row[1]), str(row[2]), str(row[3]))


def _display_name(name: str | None, email: str) -> str:
    chosen = (name or "").strip() or email.split("@", 1)[0]
    return chosen[:60]


def _create_learner(connection: Connection, display_name: str, role: str, now: datetime) -> Learner:
    learner_uuid = str(uuid.uuid4())
    learner_id = connection.execute(
        text("INSERT INTO identity_learner (uuid, display_name, role, created_at) VALUES (:uuid, :name, :role, :now) RETURNING learner_id"),
        {"uuid": learner_uuid, "name": display_name, "role": role, "now": iso(now)},
    ).scalar_one()
    return Learner(learner_id, learner_uuid, display_name, role)


def sign_in_with_google(
    connection: Connection,
    *,
    subject: str,
    email: str,
    email_verified: bool,
    name: str | None,
    owner_email: str | None,
    now: datetime,
) -> Learner:
    if not email_verified:
        raise SignInRefused("email_not_verified")

    known = connection.execute(
        text(
            "SELECT l.learner_id, l.uuid, l.display_name, l.role, l.status FROM identity_external_identity e "
            "JOIN identity_learner l USING (learner_id) WHERE e.provider = 'google' AND e.subject = :subject"
        ),
        {"subject": subject},
    ).one_or_none()
    if known is not None:
        if known.status != "active":
            raise SignInRefused("disabled")
        connection.execute(
            text(
                "UPDATE identity_external_identity SET last_used_at = :now, email = :email WHERE provider = 'google' AND subject = :subject"
            ),
            {"now": iso(now), "email": email, "subject": subject},
        )
        return _learner(known[:4])

    email_norm = normalise_email(email)
    has_owner = connection.execute(text("SELECT 1 FROM identity_learner WHERE role = 'owner'")).first() is not None
    if owner_email and email_norm == normalise_email(owner_email) and not has_owner:
        learner = _create_learner(connection, _display_name(name, email), "owner", now)
    else:
        invitation_id = connection.execute(
            text(
                "SELECT invitation_id FROM identity_invitation WHERE email_norm = :email AND accepted_at IS NULL "
                "AND revoked_at IS NULL AND expires_at > :now ORDER BY created_at DESC LIMIT 1"
            ),
            {"email": email_norm, "now": iso(now)},
        ).scalar_one_or_none()
        if invitation_id is None:
            raise SignInRefused("not_invited")
        learner = _create_learner(connection, _display_name(name, email), "learner", now)
        connection.execute(
            text("UPDATE identity_invitation SET accepted_at = :now, accepted_learner_id = :learner WHERE invitation_id = :id"),
            {"now": iso(now), "learner": learner.learner_id, "id": invitation_id},
        )

    connection.execute(
        text(
            "INSERT INTO identity_external_identity (learner_id, provider, subject, email, email_verified, created_at, last_used_at) "
            "VALUES (:learner, 'google', :subject, :email, 1, :now, :now)"
        ),
        {"learner": learner.learner_id, "subject": subject, "email": email, "now": iso(now)},
    )
    return learner


# --- sign-in sessions


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _device_kind(user_agent: str | None) -> str:
    agent = user_agent or ""
    if "iPad" in agent or "Tablet" in agent:
        return "tablet"
    if "Mobile" in agent or "Android" in agent:
        return "phone"
    return "desktop"


def start_session(connection: Connection, learner: Learner, user_agent: str | None, now: datetime) -> str:
    """Makes a sign-in session and returns its token. Only a hash of the token is stored."""
    token = secrets.token_urlsafe(32)
    connection.execute(
        text(
            "INSERT INTO identity_auth_session (learner_id, token_hash, device_kind, user_agent, created_at, last_seen_at, expires_at) "
            "VALUES (:learner, :hash, :device, :agent, :now, :now, :expires)"
        ),
        {
            "learner": learner.learner_id,
            "hash": _token_hash(token),
            "device": _device_kind(user_agent),
            "agent": (user_agent or "")[:200] or None,
            "now": iso(now),
            "expires": iso(now + timedelta(days=SESSION_DAYS)),
        },
    )
    return token


def learner_for_session(connection: Connection, token: str, now: datetime) -> Learner | None:
    """The learner of a valid session. The session is extended to 30 days from now."""
    row = connection.execute(
        text(
            "SELECT s.auth_session_id, l.learner_id, l.uuid, l.display_name, l.role FROM identity_auth_session s "
            "JOIN identity_learner l USING (learner_id) WHERE s.token_hash = :hash AND s.revoked_at IS NULL "
            "AND s.expires_at > :now AND l.status = 'active'"
        ),
        {"hash": _token_hash(token), "now": iso(now)},
    ).one_or_none()
    if row is None:
        return None
    connection.execute(
        text("UPDATE identity_auth_session SET last_seen_at = :now, expires_at = :expires WHERE auth_session_id = :id"),
        {"now": iso(now), "expires": iso(now + timedelta(days=SESSION_DAYS)), "id": row.auth_session_id},
    )
    return _learner(row[1:])


def end_session(connection: Connection, token: str, now: datetime) -> None:
    connection.execute(
        text("UPDATE identity_auth_session SET revoked_at = :now WHERE token_hash = :hash AND revoked_at IS NULL"),
        {"now": iso(now), "hash": _token_hash(token)},
    )


# --- invitations


def invite(connection: Connection, inviter: Learner, email: str, now: datetime) -> Invitation:
    if inviter.role != "owner":
        raise NotAllowed("Only the owner can invite learners")
    email_norm = normalise_email(email)
    expires = now + timedelta(days=INVITATION_DAYS)
    # A new invitation to the same address replaces an open one.
    connection.execute(
        text("UPDATE identity_invitation SET revoked_at = :now WHERE email_norm = :email AND accepted_at IS NULL AND revoked_at IS NULL"),
        {"now": iso(now), "email": email_norm},
    )
    connection.execute(
        text(
            "INSERT INTO identity_invitation (email_norm, invited_by_learner_id, created_at, expires_at) "
            "VALUES (:email, :inviter, :now, :expires)"
        ),
        {"email": email_norm, "inviter": inviter.learner_id, "now": iso(now), "expires": iso(expires)},
    )
    return Invitation(email_norm, iso(now), iso(expires), "open")


def list_invitations(connection: Connection, viewer: Learner, now: datetime) -> list[Invitation]:
    if viewer.role != "owner":
        raise NotAllowed("Only the owner can see invitations")
    rows = connection.execute(
        text("SELECT email_norm, created_at, expires_at, accepted_at, revoked_at FROM identity_invitation ORDER BY created_at DESC")
    ).all()

    def status(accepted: str | None, revoked: str | None, expires: str) -> str:
        if accepted:
            return "accepted"
        if revoked:
            return "withdrawn"
        return "expired" if expires <= iso(now) else "open"

    return [Invitation(r.email_norm, r.created_at, r.expires_at, status(r.accepted_at, r.revoked_at, r.expires_at)) for r in rows]
