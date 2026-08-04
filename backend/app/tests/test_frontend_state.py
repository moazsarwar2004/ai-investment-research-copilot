"""Streamlit state tests kept independent of the UI runtime."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from frontend.state import (
    ResearchViewState,
    classify_crypto_state,
    classify_research_state,
)

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
    assert [item.value for item in app.title] == ["Investment Research Co-Pilot"]
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


def test_crypto_ui_states_include_stale_and_partial_contracts() -> None:
    assert classify_crypto_state(None).state is ResearchViewState.EMPTY
    assert (
        classify_crypto_state(
            {
                "meta": {
                    "freshness": "delayed",
                    "cache_status": "miss",
                    "partial": True,
                }
            }
        ).state
        is ResearchViewState.PARTIAL
    )
    assert (
        classify_crypto_state(
            {
                "meta": {
                    "freshness": "stale",
                    "cache_status": "stale",
                    "partial": False,
                }
            }
        ).state
        is ResearchViewState.STALE
    )


def test_streamlit_page_renders_cached_crypto_research_without_exceptions() -> None:
    app = AppTest.from_file(str(_FRONTEND_APP))
    app.session_state["research_mode"] = "General crypto"
    app.session_state["crypto_research_payload"] = {
        "data": {
            "coin_id": "bitcoin",
            "days": 90,
            "overview": {
                "name": "Bitcoin",
                "symbol": "BTC",
                "current_price": "119000.25",
                "market_cap": "2360000000000",
                "market_cap_rank": 1,
                "total_volume_24h": "45600000000",
                "distance_from_ath_percent": "5.55",
            },
            "history": None,
            "technicals": None,
            "anomalies": None,
            "risk": {
                "overall_score": 25,
                "risk_label": "moderate",
                "component_scores": {"market_size": 10, "liquidity": 40},
                "component_weights": {"market_size": 0.5, "liquidity": 0.5},
                "methodology_version": "crypto-risk-v1",
                "data_confidence": 0.3,
                "missing_inputs": ["volatility"],
                "limitations": ["Fixture research only."],
            },
            "attribution": "Powered by CoinGecko",
            "disclaimer": "Research and education only.",
        },
        "meta": {
            "source": "coingecko",
            "freshness": "cached",
            "cache_status": "hit",
            "partial": True,
            "staleness_seconds": 120,
            "warnings": [],
            "sources": [],
        },
    }
    app.session_state["crypto_research_error"] = None

    app.run(timeout=20)

    assert not app.exception
    assert any("Powered by CoinGecko" in item.value for item in app.markdown)
    assert any("Some crypto research" in item.value for item in app.warning)
