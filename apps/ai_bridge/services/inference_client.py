from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


DEFAULT_BASE_URL = "http://192.168.6.20:8000"
DEFAULT_TIMEOUT_SECONDS = 10


class InferenceClientError(Exception):
    """AI 推論主機 API Client 基礎例外。"""


class InferenceConnectionError(InferenceClientError):
    """無法連線至 AI 推論主機。"""


class InferenceTimeoutError(InferenceClientError):
    """AI 推論主機 API 請求逾時。"""


class InferenceHTTPError(InferenceClientError):
    """AI 推論主機回傳非成功 HTTP 狀態。"""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class InferenceResponseError(InferenceClientError):
    """AI 推論主機回傳的資料格式無效。"""


@dataclass(frozen=True)
class InferenceClientConfig:
    base_url: str = DEFAULT_BASE_URL
    timeout: int = DEFAULT_TIMEOUT_SECONDS


class InferenceClient:
    """
    KRTC 正式 AI 推論主機唯讀 API Client。

    本類別只負責：
    - HTTP GET
    - timeout
    - 連線錯誤
    - HTTP 狀態檢查
    - JSON 解析
    - 基本回傳格式驗證

    不負責：
    - Django ORM
    - Event 建立
    - BroadcastRule
    - BroadcastLog
    - Camera Mapping
    - Event Mapping
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")

        if not normalized_base_url:
            raise ValueError("base_url 不可為空。")

        if timeout <= 0:
            raise ValueError("timeout 必須大於 0。")

        self.config = InferenceClientConfig(
            base_url=normalized_base_url,
            timeout=timeout,
        )

    def health(self) -> dict[str, Any]:
        """
        呼叫 GET /health。

        預期格式：
        {
            "status": "ok"
        }
        """
        payload = self._get_json("/health")

        if not isinstance(payload, dict):
            raise InferenceResponseError(
                "/health 回傳格式錯誤，預期為 JSON object。"
            )

        return payload

    def is_healthy(self) -> bool:
        """
        檢查推論主機是否回傳 status=ok。

        API 或網路錯誤仍會拋出例外，不會直接吞掉錯誤。
        """
        payload = self.health()
        return payload.get("status") == "ok"

    def get_events(
        self,
        *,
        camera_id: str | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        呼叫 GET /api/events。

        第一版只做唯讀抓取及格式驗證，不做 Mapping 或資料庫寫入。
        """
        if limit <= 0:
            raise ValueError("limit 必須大於 0。")

        if offset < 0:
            raise ValueError("offset 不可小於 0。")

        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }

        optional_params = {
            "camera_id": camera_id,
            "event_type": event_type,
            "severity": severity,
            "since": since,
            "until": until,
        }

        for key, value in optional_params.items():
            if value is not None and value != "":
                params[key] = value

        payload = self._get_json("/api/events", params=params)

        self._validate_collection_response(
            payload=payload,
            endpoint="/api/events",
        )

        return payload

    def get_event(self, event_id: int | str) -> dict[str, Any]:
        """
        呼叫 GET /api/events/{id}。
        """
        if str(event_id).strip() == "":
            raise ValueError("event_id 不可為空。")

        safe_event_id = parse.quote(str(event_id).strip(), safe="")
        payload = self._get_json(f"/api/events/{safe_event_id}")

        if not isinstance(payload, dict):
            raise InferenceResponseError(
                "/api/events/{id} 回傳格式錯誤，預期為 JSON object。"
            )

        return payload

    def get_cameras(self) -> Any:
        """
        呼叫 GET /api/cameras。

        文件預期可能為：
        {
            "total": 2,
            "items": [...]
        }

        但正式主機目前 PowerShell 顯示為空集合，因此此處先保留
        list 或 dict，不做過度嚴格的格式限制。
        """
        payload = self._get_json("/api/cameras")

        if not isinstance(payload, (dict, list)):
            raise InferenceResponseError(
                "/api/cameras 回傳格式錯誤，預期為 JSON object 或 array。"
            )

        return payload

    def build_snapshot_url(self, snapshot_path: str | None) -> str | None:
        """
        將 snapshot_path 組成完整 Snapshot URL。

        若 snapshot_path 已是完整 HTTP/HTTPS URL，則直接回傳。
        若為空或 null，則回傳 None。
        """
        if snapshot_path is None:
            return None

        normalized_path = snapshot_path.strip()

        if not normalized_path:
            return None

        if normalized_path.startswith(("http://", "https://")):
            return normalized_path

        normalized_path = normalized_path.lstrip("/")

        if normalized_path.startswith("snapshots/"):
            return f"{self.config.base_url}/{normalized_path}"

        return f"{self.config.base_url}/snapshots/{normalized_path}"

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = self._build_url(path=path, params=params)

        http_request = request.Request(
            url=url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "KRTC-Notification-Host/2.0",
            },
        )

        try:
            with request.urlopen(
                http_request,
                timeout=self.config.timeout,
            ) as response:
                status_code = response.getcode()
                response_body = response.read().decode("utf-8")

        except error.HTTPError as exc:
            error_body = self._read_http_error_body(exc)

            raise InferenceHTTPError(
                status_code=exc.code,
                message=(
                    f"推論主機 HTTP 錯誤："
                    f"status={exc.code}, url={url}, body={error_body}"
                ),
            ) from exc

        except (socket.timeout, TimeoutError) as exc:
            raise InferenceTimeoutError(
                f"推論主機請求逾時：url={url}, timeout={self.config.timeout}s"
            ) from exc

        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)

            if isinstance(reason, socket.timeout):
                raise InferenceTimeoutError(
                    f"推論主機請求逾時："
                    f"url={url}, timeout={self.config.timeout}s"
                ) from exc

            raise InferenceConnectionError(
                f"無法連線至推論主機：url={url}, reason={reason}"
            ) from exc

        except OSError as exc:
            raise InferenceConnectionError(
                f"推論主機連線失敗：url={url}, reason={exc}"
            ) from exc

        if not 200 <= status_code < 300:
            raise InferenceHTTPError(
                status_code=status_code,
                message=(
                    f"推論主機回傳非成功狀態："
                    f"status={status_code}, url={url}"
                ),
            )

        try:
            return json.loads(response_body)

        except json.JSONDecodeError as exc:
            preview = response_body[:500]

            raise InferenceResponseError(
                f"推論主機回傳非有效 JSON：url={url}, body={preview}"
            ) from exc

    def _build_url(
        self,
        *,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        normalized_path = "/" + path.lstrip("/")
        url = f"{self.config.base_url}{normalized_path}"

        if params:
            query_string = parse.urlencode(params)
            url = f"{url}?{query_string}"

        return url

    @staticmethod
    def _validate_collection_response(
        *,
        payload: Any,
        endpoint: str,
    ) -> None:
        if not isinstance(payload, dict):
            raise InferenceResponseError(
                f"{endpoint} 回傳格式錯誤，預期為 JSON object。"
            )

        if "items" not in payload:
            raise InferenceResponseError(
                f"{endpoint} 回傳缺少 items 欄位。"
            )

        if not isinstance(payload["items"], list):
            raise InferenceResponseError(
                f"{endpoint} 的 items 必須為 JSON array。"
            )

        if "total" in payload and not isinstance(payload["total"], int):
            raise InferenceResponseError(
                f"{endpoint} 的 total 必須為整數。"
            )

    @staticmethod
    def _read_http_error_body(exc: error.HTTPError) -> str:
        try:
            return exc.read().decode("utf-8")[:500]
        except Exception:
            return "<無法讀取錯誤內容>"