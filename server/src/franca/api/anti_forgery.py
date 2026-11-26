"""Protection against forged requests (story E02-003): the double-submit pattern.

Every API answer to a browser that has no franca_csrf cookie gives it one, with a random token. A request that
changes something (any method but GET, HEAD and OPTIONS) has to send the same token in the X-CSRF-Token header.
Another site can make the browser send a request with Franca's cookies, but it cannot read the cookie, so it cannot
put the token in the header. The cookie is readable by the page's script on purpose, and is SameSite=Strict.
"""

import hmac
import json
import secrets
from http.cookies import SimpleCookie
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

COOKIE = "franca_csrf"
HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _cookies(scope: Scope) -> dict[str, str]:
    jar: SimpleCookie = SimpleCookie()
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            try:
                jar.load(bytes(value).decode("latin-1"))
            except Exception:  # noqa: BLE001 - a malformed Cookie header is treated as no cookies
                return {}
    return {key: morsel.value for key, morsel in jar.items()}


def _header(scope: Scope, wanted: bytes) -> str | None:
    for name, value in scope.get("headers", []):
        if name == wanted:
            return bytes(value).decode("latin-1")
    return None


class AntiForgeryMiddleware:
    def __init__(self, app: ASGIApp, *, secure: bool, prefix: str = "/api/") -> None:
        self.app = app
        self.secure = secure
        self.prefix = prefix

    def _set_cookie(self, token: str) -> tuple[bytes, bytes]:
        parts = [f"{COOKIE}={token}", "Path=/", "SameSite=strict", "Max-Age=31536000"]
        if self.secure:
            parts.append("Secure")
        return b"set-cookie", "; ".join(parts).encode("latin-1")

    async def _refuse(self, send: Send, reason: str, new_token: str | None) -> None:
        headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
        if new_token:
            headers.append(self._set_cookie(new_token))
        await send({"type": "http.response.start", "status": 403, "headers": headers})
        await send({"type": "http.response.body", "body": json.dumps({"detail": reason}).encode()})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith(self.prefix):
            await self.app(scope, receive, send)
            return
        token = _cookies(scope).get(COOKIE)
        new_token = None if token else secrets.token_urlsafe(32)
        if scope["method"] not in SAFE_METHODS:
            sent = _header(scope, HEADER.encode())
            if not token or not sent:
                await self._refuse(send, "anti-forgery-token-missing", new_token)
                return
            if not hmac.compare_digest(token.encode(), sent.encode()):
                await self._refuse(send, "anti-forgery-token-wrong", None)
                return
        if new_token is None:
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[Any] = list(message.get("headers", []))
                headers.append(self._set_cookie(new_token))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)
