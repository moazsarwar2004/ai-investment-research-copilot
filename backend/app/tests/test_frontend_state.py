"""Streamlit state tests kept independent of the UI runtime."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from frontend.state import ResearchViewState, classify_research_state

_FRONTEND_APP = Path(__file__).parents[3] / "frontend" / "app.py"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (None, ResearchViewState.EMPTY),
        (
            {"meta": {"freshness": "live", "cache_status": "miss", "partial": False}},
            ResearchViewState.READY,
        ),
        (
            {"meta": {"freshness": "live", "cache_status": "hit", "partial": True}},
            ResearchViewState.PARTIAL,
        ),
        (
            {
                "meta": {
                    "freshness": "stale",
                    "cache_status": "stale",
                    "partial": False,
                }
            },
            ResearchViewState.STALE,
        ),
    ],
)
def test_research_ui_states(
    payload: dict[str, object] | None,
    expected: ResearchViewState,
) -> None:
    assert classify_research_state(payload).state is expected


def test_research_ui_error_state_is_prominent() -> None:
    state = classify_research_state(None, error="Provider unavailable.")

    assert state.state is ResearchViewState.ERROR
    assert state.message == "Provider unavailable."


def test_streamlit_page_renders_empty_state_without_exceptions() -> None:
    app = AppTest.from_file(str(_FRONTEND_APP)).run(timeout=20)

    assert not app.exception
    assert [item.value for item in app.title] == ["Binance Spot Research"]
    assert any("Choose a Spot pair" in item.value for item in app.info)


def test_streamlit_page_renders_completed_research_without_exceptions() -> None:
    app = AppTest.from_file(str(_FRONTEND_APP))
    app.session_state["research_payload"] = {
        "data": {
            "symbol": "BTCUSDT",
            "ticker": {"last_price": "100.00"},
            "disclaimer": "Research and education only.",
        },
        "meta": {
            "freshness": "live",
            "cache_status": "miss",
            "partial": False,
            "staleness_seconds": 0,
            "warnings": [],
            "sources": [],
        },
    }
    app.session_state["research_error"] = None

    app.run(timeout=20)

    assert not app.exception
    assert any("Fresh research snapshot loaded" in item.value for item in app.success)
    assert any("Research and education only" in item.value for item in app.warning)
