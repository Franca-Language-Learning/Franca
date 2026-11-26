"""A software passkey device for tests: it answers the browser's WebAuthn calls as a phone or laptop would.

It makes an ES256 key pair, and builds the registration and sign-in responses that a browser sends to the server
(the JSON form of PublicKeyCredential), with "none" attestation. The server checks them with py_webauthn as it
checks a real device's answers.
"""

import base64
import hashlib
import json
import secrets
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

UP, UV, BE, BS, AT = 0x01, 0x04, 0x08, 0x10, 0x40


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class PasskeyDevice:
    def __init__(self, origin: str, *, backed_up: bool = True, user_verified: bool = True) -> None:
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(32)
        self.sign_count = 0
        self.user_handle = b""
        self.flags = UP | (UV if user_verified else 0) | ((BE | BS) if backed_up else 0)

    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin or self.origin, "crossOrigin": False}).encode()

    def register(self, options: dict[str, Any], *, origin: str | None = None, rp_id: str | None = None) -> dict[str, Any]:
        """The answer to navigator.credentials.create() with the given creation options."""
        self.user_handle = unb64url(options["user"]["id"])
        rp_hash = hashlib.sha256((rp_id or options["rp"]["id"]).encode()).digest()
        attested = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose_key()
        auth_data = rp_hash + bytes([self.flags | AT]) + struct.pack(">I", self.sign_count) + attested
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(self._client_data("webauthn.create", options["challenge"], origin)),
                "attestationObject": b64url(attestation),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

    def sign_in(
        self, options: dict[str, Any], *, origin: str | None = None, sign_count: int | None = None, user_handle: bytes | None = None
    ) -> dict[str, Any]:
        """The answer to navigator.credentials.get() with the given request options."""
        self.sign_count = self.sign_count + 1 if sign_count is None else sign_count
        rp_hash = hashlib.sha256(options["rpId"].encode()).digest()
        auth_data = rp_hash + bytes([self.flags]) + struct.pack(">I", self.sign_count)
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": b64url(self.user_handle if user_handle is None else user_handle),
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }
