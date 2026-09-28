"""Low-cardinality in-process request metrics for the single-worker pilot."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class RequestMetrics:
    """Collect bounded route-template counters without user or asset labels."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self._duration_count: dict[tuple[str, str], int] = defaultdict(int)

    def observe(
        self, *, method: str, route: str, status_code: int, duration_seconds: float
    ) -> None:
        normalized_method = method.upper()[:12]
        normalized_route = route[:160]
        with self._lock:
            self._counts[(normalized_method, normalized_route, status_code)] += 1
            key = (normalized_method, normalized_route)
            self._duration_sum[key] += max(0.0, duration_seconds)
            self._duration_count[key] += 1

    def render(self) -> str:
        with self._lock:
            counts = dict(self._counts)
            duration_sum = dict(self._duration_sum)
            duration_count = dict(self._duration_count)
        lines = [
            "# HELP copilot_http_requests_total HTTP requests by route template.",
            "# TYPE copilot_http_requests_total counter",
        ]
        for (method, route, status_code), count in sorted(counts.items()):
            lines.append(
                "copilot_http_requests_total"
                f'{{method="{_label(method)}",route="{_label(route)}",'
                f'status="{status_code}"}} {count}'
            )
        lines.extend(
            [
                "# HELP copilot_http_request_duration_seconds Request duration.",
                "# TYPE copilot_http_request_duration_seconds summary",
            ]
        )
        for (method, route), count in sorted(duration_count.items()):
            labels = f'method="{_label(method)}",route="{_label(route)}"'
            lines.append(
                "copilot_http_request_duration_seconds_count" f"{{{labels}}} {count}"
            )
            lines.append(
                "copilot_http_request_duration_seconds_sum"
                f"{{{labels}}} {duration_sum[(method, route)]:.6f}"
            )
        return "\n".join(lines) + "\n"


__all__ = ["RequestMetrics"]
