"""Protection against forged requests (story E02-003): the double-submit pattern.

Every API answer to a browser that has no franca_csrf cookie gives it one, with a random token. A request that
changes something (any method but GET, HEAD and OPTIONS) has to send the same token in the X-CSRF-Token header.
Another site can make the browser send a request with Franca's cookies, but it cannot read the cookie, so it cannot
put the token in the header. The cookie is readable by the page's script on purpose, and is SameSite=Strict.

Over https the cookie is called __Host-franca_csrf, so another computer in the same tailnet cannot set it. A change
that the browser marks as coming from another origin (Sec-Fetch-Site) is refused as well. The check applies to every
path; the cookie is given with answers under /api/.
"""

import hmac
import json
import secrets
from typing import Any

from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

COOKIE = "franca_csrf"
SECURE_PREFIX = "__Host-"
HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Values of Sec-Fetch-Site for a request from Franca's own pages, or one the person typed or bookmarked.
OWN_ORIGIN = frozenset({"same-origin", "none"})


def cookie_name(secure: bool) -> str:
    return SECURE_PREFIX + COOKIE if secure else COOKIE


def _cookies(scope: Scope) -> dict[str, str]:
    # The same parser as Starlette's request.cookies, which reads the session cookie, so the two agree.
    joined = "; ".join(bytes(value).decode("latin-1") for name, value in scope.get("headers", []) if name == b"cookie")
    return cookie_parser(joined)


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
        parts = [f"{cookie_name(self.secure)}={token}", "Path=/", "SameSite=strict", "Max-Age=31536000"]
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
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _cookies(scope).get(cookie_name(self.secure))
        gives_cookie = str(scope.get("path", "")).startswith(self.prefix)
        new_token = None if token or not gives_cookie else secrets.token_urlsafe(32)
        if scope["method"] not in SAFE_METHODS:
            site = _header(scope, b"sec-fetch-site")
            if site is not None and site not in OWN_ORIGIN:
                await self._refuse(send, "cross-site-request", None)
                return
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
