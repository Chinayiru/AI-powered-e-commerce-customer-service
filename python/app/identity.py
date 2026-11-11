"""HMAC internal identity shared with the Java control plane.

Wire format: ``base64url(JSON{userId,role,exp,nonce}) + "." + base64url(HMAC)``.
The signature covers the encoded payload string, exactly like Java's
`HmacService`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import uuid
from dataclasses import dataclass

_ALLOWED_ROLES = {"agent", "python", "system", "service"}


class IdentityError(Exception):
    """The header is missing, malformed, expired, or replayed."""


@dataclass(frozen=True)
class Identity:
    userId: str
    role: str
    exp: int
    nonce: str


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def issue_identity(user_id: str, role: str, secret: str, ttl_seconds: int = 300) -> str:
    if role not in _ALLOWED_ROLES:
        raise ValueError(f"unsupported internal role: {role}")
    payload = json.dumps(
        {
            "userId": user_id,
            "role": role,
            "exp": int(time.time()) + ttl_seconds,
            "nonce": str(uuid.uuid4()),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    encoded = _b64url_encode(payload.encode("utf-8"))
    return f"{encoded}.{_sign(encoded, secret)}"


class NonceCache:
    """Small in-process replay cache keyed by nonce + identity + path."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()

    def remember(self, key: str, exp: int) -> None:
        now = int(time.time())
        with self._lock:
            previous = self._seen.get(key)
            if previous is not None and previous >= now:
                raise IdentityError("internal identity nonce replayed")
            self._seen[key] = exp
            if len(self._seen) > 10_000:
                self._seen = {k: v for k, v in self._seen.items() if v >= now}


_DEFAULT_NONCES = NonceCache()


def verify_identity(
    header: str | None,
    path: str,
    secret: str,
    nonces: NonceCache | None = None,
) -> Identity:
    if not header:
        raise IdentityError("missing internal identity")
    parts = header.strip().split(".")
    if len(parts) != 2:
        raise IdentityError("malformed internal identity")
    encoded, signature = parts
    if not hmac.compare_digest(_sign(encoded, secret), signature):
        raise IdentityError("invalid internal identity signature")
    try:
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
        user_id = str(payload["userId"])
        role = str(payload["role"])
        exp = int(payload["exp"])
        nonce = str(payload["nonce"])
    except Exception as exc:  # noqa: BLE001 - contract boundary
        raise IdentityError("invalid internal identity payload") from exc
    if not user_id or role not in _ALLOWED_ROLES or not nonce or exp < int(time.time()):
        raise IdentityError("expired or incomplete internal identity")
    (nonces or _DEFAULT_NONCES).remember(f"{nonce}|{user_id}|{role}|{path}", exp)
    return Identity(userId=user_id, role=role, exp=exp, nonce=nonce)
