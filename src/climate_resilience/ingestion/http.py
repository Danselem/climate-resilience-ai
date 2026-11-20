"""HTTP retrieval with hashing and retries.

Raw responses are written once, hashed, and never mutated. Every download
produces a ``DownloadResult`` that becomes a catalogue and manifest entry.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..envelope import now_utc
from ..manifest import sha256_file

USER_AGENT = "climate-resilience-ai/0.1 (+pilot; contact: project maintainer)"
DEFAULT_TIMEOUT = 90.0


@dataclass(frozen=True)
class DownloadResult:
    url: str
    path: Path
    sha256: str
    bytes: int
    retrieved_at: str


def download(
    url: str,
    dest: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 3,
    backoff_seconds: float = 3.0,
) -> DownloadResult:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = client.get(url)
                response.raise_for_status()
            dest.write_bytes(response.content)
            return DownloadResult(
                url=url,
                path=dest,
                sha256=sha256_file(dest),
                bytes=dest.stat().st_size,
                retrieved_at=now_utc().isoformat(),
            )
        except (httpx.HTTPError, OSError) as exc:  # network or disk
            last_error = exc
            if attempt < retries:
                time.sleep(backoff_seconds * attempt)

    raise RuntimeError(f"download failed after {retries} attempts: {url}") from last_error


def get_json(url: str, *, timeout: float = DEFAULT_TIMEOUT, retries: int = 3) -> object:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(3.0 * attempt)
    raise RuntimeError(f"request failed after {retries} attempts: {url}") from last_error
