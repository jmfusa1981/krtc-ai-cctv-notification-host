from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone


def body_sha256(body: bytes) -> str:
    """計算實際送出 UTF-8 body 的 SHA-256 小寫十六進位值。"""

    return hashlib.sha256(body).hexdigest()


def generate_timestamp(now: datetime | None = None) -> str:
    """產生帶 UTC timezone 的 ISO-8601 timestamp。"""

    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_nonce() -> str:
    """產生不依賴全域狀態的隨機 request nonce。"""

    return secrets.token_hex(16)


def generate_request_id() -> str:
    """產生符合 common payload contract 的 UUID。"""

    return str(uuid.uuid4())


def canonical_string(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body_hash: str,
) -> str:
    """依 Integration Contract v1.0 固定順序建立簽章文字。"""

    return "\n".join(
        (
            str(method).upper(),
            str(path),
            str(timestamp),
            str(nonce),
            str(body_hash).lower(),
        )
    )


def sign_canonical(shared_secret: str, value: str) -> str:
    """使用 HMAC-SHA256 產生小寫十六進位簽章。"""

    return hmac.new(
        shared_secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_signed_headers(
    *,
    method: str,
    path: str,
    body: bytes,
    station_code: str,
    host_code: str,
    shared_secret: str,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """建立單一 request 所需的安全 headers，不保存密鑰。"""

    request_timestamp = timestamp or generate_timestamp()
    request_nonce = nonce or generate_nonce()
    digest = body_sha256(body)
    canonical = canonical_string(
        method,
        path,
        request_timestamp,
        request_nonce,
        digest,
    )
    signature = sign_canonical(shared_secret, canonical)
    return {
        "Content-Type": "application/json; charset=utf-8",
        "X-KRTC-Station": station_code,
        "X-KRTC-Host": host_code,
        "X-KRTC-Timestamp": request_timestamp,
        "X-KRTC-Nonce": request_nonce,
        "X-KRTC-Signature": signature,
    }
