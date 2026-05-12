from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass


HASH_NAME = "sha256"
HASH_ITERATIONS = 240_000
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30


@dataclass(frozen=True)
class TokenPayload:
    username: str
    expires_at: int


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        HASH_NAME,
        password.encode("utf-8"),
        salt,
        HASH_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        HASH_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(digest_text.encode("ascii"))
    except (ValueError, TypeError):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        HASH_NAME,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def create_token(username: str, secret: str) -> str:
    payload = {
        "username": username,
        "expires_at": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_text = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
    signature = _sign(payload_text, secret)
    return f"{payload_text}.{signature}"


def parse_token(token: str, secret: str) -> TokenPayload | None:
    try:
        payload_text, signature = token.split(".", 1)
    except ValueError:
        return None

    if not hmac.compare_digest(_sign(payload_text, secret), signature):
        return None

    try:
        payload_bytes = base64.urlsafe_b64decode(payload_text.encode("ascii"))
        payload = json.loads(payload_bytes.decode("utf-8"))
        username = str(payload["username"])
        expires_at = int(payload["expires_at"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None

    if expires_at < int(time.time()):
        return None

    return TokenPayload(username=username, expires_at=expires_at)


def _sign(payload_text: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        payload_text.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")
