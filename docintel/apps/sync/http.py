"""HTTP delivery. The transport is injectable so tests never open a socket."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Mapping

from docintel.apps.sync.mapping import DeliveryResult

_MAX_BODY = 2_000


def post_json(
    *,
    url: str,
    body: bytes,
    headers: Mapping[str, str],
    timeout: float,
) -> DeliveryResult:
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers),
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_BODY)
            return DeliveryResult(
                status_code=response.status,
                body=_truncate(raw),
                latency_ms=_elapsed(started),
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read(_MAX_BODY)
        return DeliveryResult(
            status_code=exc.code,
            body=_truncate(raw),
            latency_ms=_elapsed(started),
        )
    except urllib.error.URLError as exc:
        return DeliveryResult(
            status_code=0,
            body="",
            latency_ms=_elapsed(started),
            error=str(exc.reason),
        )


def _truncate(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")[:_MAX_BODY]


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
