from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


DEFAULT_ALERTS_PATH = "/ws/alerts"
_HTTP_URL_VALIDATOR = URLValidator(schemes=["http", "https"])
_WEBSOCKET_URL_VALIDATOR = URLValidator(schemes=["ws"])


def build_websocket_url(base_url: str, path: str = DEFAULT_ALERTS_PATH) -> str:
    """依 Base URL 主機與連接埠建立本版唯一支援的 ws URL。"""
    parsed = _split_url(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Base URL 必須使用 http:// 或 https://。")
    _validate_url(base_url, _HTTP_URL_VALIDATOR, "Base URL 格式不正確。")

    normalized_path = f"/{path.lstrip('/')}"
    return urlunsplit(("ws", parsed.netloc, normalized_path, "", ""))


def validate_websocket_url(value: str) -> str:
    """驗證並回傳可供 consumer 使用的明確 WebSocket URL。"""
    normalized = value.strip()
    parsed = _split_url(normalized)
    if parsed.scheme != "ws":
        raise ValueError("目前系統僅支援 ws:// WebSocket 連線。")
    _validate_url(normalized, _WEBSOCKET_URL_VALIDATOR, "WebSocket URL 格式不正確。")
    if parsed.fragment:
        raise ValueError("WebSocket URL 不可包含 fragment。")
    return normalized


def _split_url(value: str):
    normalized = (value or "").strip()
    if not normalized or any(character.isspace() for character in normalized):
        raise ValueError("URL 格式不正確。")

    try:
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise ValueError("URL 格式不正確。") from exc

    if not parsed.netloc or not hostname:
        raise ValueError("URL 必須包含有效主機名稱。")
    return parsed


def _validate_url(value: str, validator: URLValidator, message: str) -> None:
    try:
        validator(value)
    except ValidationError as exc:
        raise ValueError(message) from exc
