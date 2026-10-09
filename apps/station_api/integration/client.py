from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests

from .config import OccIntegrationConfig
from .signing import build_signed_headers


RETRYABLE_HTTP_STATUSES = {429}
NON_RETRYABLE_HTTP_STATUSES = {400, 401, 403, 404, 422}


@dataclass(frozen=True)
class OccError:
    """供 Phase P2 queue 判斷 retry 的結構化錯誤。"""

    code: str
    message: str
    retryable: bool
    http_status: int | None = None


@dataclass(frozen=True)
class OccResult:
    """統一表示 OCC ACK 或可分類的失敗。"""

    success: bool
    request_id: str
    http_status: int | None = None
    received_at: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: OccError | None = None

    @property
    def retryable(self) -> bool:
        """讓未來 queue 不需解析錯誤訊息即可分類。"""

        return bool(self.error and self.error.retryable)


def encode_json_body(payload: dict) -> bytes:
    """以固定 UTF-8 JSON bytes 同時供簽章與 HTTP body 使用。"""

    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _parse_received_at(value) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("received_at must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("received_at must include a timezone")
    return value


class OccHttpClient:
    """只允許向已設定 OCC base URL 送出簽章 JSON request。"""

    def __init__(self, config=None, session=None):
        self.config = config or OccIntegrationConfig.from_settings()
        self.session = session or requests.Session()

    def post_json(self, path: str, payload: dict) -> OccResult:
        """送出有界 timeout 的 HMAC request 並嚴格驗證 ACK。"""

        request_id = str(payload.get("request_id") or "")
        if not self.config.configured:
            return self._failure(
                request_id,
                "configuration_incomplete",
                "OCC integration configuration is incomplete.",
                False,
            )
        if not path.startswith("/") or not path.startswith("/api/v1/"):
            return self._failure(
                request_id,
                "invalid_path",
                "OCC path must be under /api/v1/.",
                False,
            )

        body = encode_json_body(payload)
        headers = build_signed_headers(
            method="POST",
            path=path,
            body=body,
            station_code=self.config.station_code,
            host_code=self.config.host_code,
            shared_secret=self.config.shared_secret,
        )
        endpoint = urljoin(f"{self.config.base_url}/", path.lstrip("/"))
        try:
            response = self.session.post(
                endpoint,
                data=body,
                headers=headers,
                timeout=(
                    self.config.connect_timeout,
                    self.config.read_timeout,
                ),
            )
        except requests.ConnectTimeout:
            return self._failure(
                request_id,
                "connect_timeout",
                "OCC connection timed out.",
                True,
            )
        except requests.ReadTimeout:
            return self._failure(
                request_id,
                "read_timeout",
                "OCC response timed out.",
                True,
            )
        except requests.Timeout:
            return self._failure(
                request_id,
                "network_timeout",
                "OCC request timed out.",
                True,
            )
        except requests.RequestException:
            return self._failure(
                request_id,
                "network_error",
                "OCC network request failed.",
                True,
            )

        if not 200 <= response.status_code < 300:
            retryable = (
                response.status_code in RETRYABLE_HTTP_STATUSES
                or response.status_code >= 500
            )
            error_code = (
                "authentication_failed"
                if response.status_code in {401, 403}
                else f"http_{response.status_code}"
            )
            return self._failure(
                request_id,
                error_code,
                f"OCC returned HTTP {response.status_code}.",
                retryable,
                response.status_code,
            )

        try:
            acknowledgement = response.json()
        except (TypeError, ValueError):
            return self._failure(
                request_id,
                "malformed_json",
                "OCC response is not valid JSON.",
                False,
                response.status_code,
            )
        if not isinstance(acknowledgement, dict):
            return self._failure(
                request_id,
                "malformed_ack",
                "OCC response must be a JSON object.",
                False,
                response.status_code,
            )
        if acknowledgement.get("success") is not True:
            error = acknowledgement.get("error")
            code = str(error.get("code") if isinstance(error, dict) else "ack_failed")
            message = str(
                error.get("message") if isinstance(error, dict) else "OCC rejected request."
            )
            return self._failure(
                request_id,
                code[:100],
                message[:500],
                False,
                response.status_code,
            )
        response_request_id = acknowledgement.get("request_id")
        if response_request_id and str(response_request_id) != request_id:
            return self._failure(
                request_id,
                "request_id_mismatch",
                "OCC acknowledgement request_id does not match.",
                False,
                response.status_code,
            )
        try:
            received_at = _parse_received_at(acknowledgement.get("received_at"))
        except (TypeError, ValueError):
            return self._failure(
                request_id,
                "invalid_received_at",
                "OCC acknowledgement received_at is invalid.",
                False,
                response.status_code,
            )
        result = acknowledgement.get("result", {})
        if not isinstance(result, dict):
            return self._failure(
                request_id,
                "malformed_ack",
                "OCC acknowledgement result must be an object.",
                False,
                response.status_code,
            )
        return OccResult(
            success=True,
            request_id=request_id,
            http_status=response.status_code,
            received_at=received_at,
            result=result,
        )

    @staticmethod
    def _failure(
        request_id: str,
        code: str,
        message: str,
        retryable: bool,
        http_status: int | None = None,
    ) -> OccResult:
        return OccResult(
            success=False,
            request_id=request_id,
            http_status=http_status,
            error=OccError(
                code=code,
                message=message,
                retryable=retryable,
                http_status=http_status,
            ),
        )
