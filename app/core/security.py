import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from typing import Any


PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_encode(salt)}${_encode(digest)}"


def verify_password(password: str, encoded_password: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded_password.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(digest, _decode(expected))
    except (TypeError, ValueError):
        return False


def create_access_token(subject: str, secret: str, expires_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
        "type": "access",
    }
    header = {"alg": "HS256", "typ": "JWT"}
    segments = [_encode_json(header), _encode_json(payload)]
    signature = hmac.new(
        secret.encode("utf-8"), ".".join(segments).encode("ascii"), hashlib.sha256
    ).digest()
    return ".".join([*segments, _encode(signature)])


def decode_access_token(token: str, secret: str) -> dict[str, Any] | None:
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
        expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(signature_segment)):
            return None
        header = json.loads(_decode(header_segment))
        payload = json.loads(_decode(payload_segment))
        if header.get("alg") != "HS256" or payload.get("type") != "access":
            return None
        if int(payload["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
            return None
        if not isinstance(payload.get("sub"), str):
            return None
        return payload
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encode_json(value: dict[str, Any]) -> str:
    return _encode(json.dumps(value, separators=(",", ":"), sort_keys=True).encode())
