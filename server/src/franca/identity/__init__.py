"""Sign-in with Google and passkeys, accounts, sessions and roles.

Other modules import this module's package root only (franca.identity), never its submodules.
"""

from franca.identity.accounts import (
    INVITATION_DAYS,
    SESSION_DAYS,
    Invitation,
    Learner,
    NotAllowed,
    SessionCheck,
    SignInRefused,
    end_session,
    invite,
    learner_for_session,
    list_invitations,
    sign_in_with_google,
    start_session,
)
from franca.identity.passkeys import (
    MAX_PASSKEYS,
    Passkey,
    PasskeyChallenge,
    PasskeyNotAccepted,
    RelyingParty,
    add_passkey,
    list_passkeys,
    passkey_registration_options,
    passkey_sign_in_options,
    relying_party,
    remove_passkey,
    sign_in_with_passkey,
)

__all__ = [
    "sign_in_with_passkey",
    "remove_passkey",
    "relying_party",
    "passkey_sign_in_options",
    "passkey_registration_options",
    "list_passkeys",
    "add_passkey",
    "RelyingParty",
    "PasskeyNotAccepted",
    "PasskeyChallenge",
    "Passkey",
    "INVITATION_DAYS",
    "MAX_PASSKEYS",
    "SESSION_DAYS",
    "Invitation",
    "Learner",
    "NotAllowed",
    "SessionCheck",
    "SignInRefused",
    "end_session",
    "invite",
    "learner_for_session",
    "list_invitations",
    "sign_in_with_google",
    "start_session",
]
