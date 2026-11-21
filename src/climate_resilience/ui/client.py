"""HTTP client for the UI.

The interface reads the same API the assistant's tools back, so the UI cannot
compute a value even by accident. Every failure mode is translated into
something a planner can act on, and no exception text reaches the page.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_URL = "http://127.0.0.1:8000"
READ_TIMEOUT = 15.0
ASK_TIMEOUT = 45.0
REPORT_TIMEOUT = 120.0


class ApiError(RuntimeError):
    """Base for every failure the UI knows how to explain."""


class ApiUnavailable(ApiError):
    def __init__(self) -> None:
        super().__init__(
            "The API is not running. Start it with `make api`, then reload this page."
        )


class ApiUnauthorized(ApiError):
    def __init__(self) -> None:
        super().__init__(
            "This deployment requires an API key. Set CRP_API_KEY before starting "
            "the UI and the API."
        )


class ApiTimeout(ApiError):
    def __init__(self, seconds: float) -> None:
        super().__init__(f"The API did not answer within {seconds:.0f} s. Try again.")


class ApiRejected(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)


@dataclass
class ApiClient:
    base_url: str = DEFAULT_URL
    api_key: str | None = None

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key} if self.api_key else {}

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        query = {key: value for key, value in params.items() if value is not None}
        return self._request("GET", path, params=query, timeout=READ_TIMEOUT)

    def post(self, path: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        return self._request("POST", path, json=payload, timeout=timeout)

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self.base_url.rstrip('/')}{path}",
                headers=self._headers(),
                timeout=timeout,
                **kwargs,
            )
        except httpx.ConnectError as exc:
            raise ApiUnavailable() from exc
        except httpx.TimeoutException as exc:
            raise ApiTimeout(timeout) from exc
        if response.status_code == 401:
            raise ApiUnauthorized()
        if response.status_code >= 400:
            detail = response.json().get("detail") if response.headers.get(
                "content-type", ""
            ).startswith("application/json") else None
            raise ApiRejected(str(detail or f"HTTP {response.status_code}"))
        return response.json()

    # --- routes the pages use ---------------------------------------------
    def health(self) -> dict[str, Any]:
        return self.get("/health")

    def coverage(self) -> dict[str, Any]:
        return self.get("/coverage")

    def indicator(self, indicator_id: str, **params: Any) -> dict[str, Any]:
        return self.get(f"/indicators/{indicator_id}", **params)

    def rank(self, indicator_id: str, **params: Any) -> dict[str, Any]:
        return self.get("/rank", indicator_id=indicator_id, **params)

    def ask(self, question: str) -> dict[str, Any]:
        return self.post("/ask", {"question": question}, timeout=ASK_TIMEOUT)

    def request_report(self, scope_id: str) -> dict[str, Any]:
        return self.post(
            "/reports", {"scope_id": scope_id, "process_now": True}, timeout=REPORT_TIMEOUT
        )

    def report(self, job_id: str) -> dict[str, Any]:
        return self.get(f"/reports/{job_id}")

    def pdf_url(self, job_id: str) -> str:
        return f"{self.base_url.rstrip('/')}/reports/{job_id}/file"


def client_from_env() -> ApiClient:
    return ApiClient(
        base_url=os.environ.get("CRP_API_URL", DEFAULT_URL),
        api_key=os.environ.get("CRP_API_KEY") or None,
    )
