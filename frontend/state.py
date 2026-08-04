"""Pure UI-state classification shared by Streamlit and fixture tests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ResearchViewState(StrEnum):
    EMPTY = "empty"
    READY = "ready"
    PARTIAL = "partial"
    STALE = "stale"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ResearchState:
    state: ResearchViewState
    message: str


def classify_research_state(
    payload: dict[str, Any] | None,
    *,
    error: str | None = None,
) -> ResearchState:
    """Map API freshness and partial flags to one prominent page state."""
    if error:
        return ResearchState(ResearchViewState.ERROR, error)
    if payload is None:
        return ResearchState(
            ResearchViewState.EMPTY,
            "Choose a Spot pair and load its research snapshot.",
        )
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return ResearchState(
            ResearchViewState.ERROR,
            "The API returned a response without freshness metadata.",
        )
    freshness = meta.get("freshness")
    cache_status = meta.get("cache_status")
    if freshness == "stale" or cache_status == "stale":
        return ResearchState(
            ResearchViewState.STALE,
            "Showing a stale cached snapshot because Binance refresh failed.",
        )
    if meta.get("partial") is True:
        return ResearchState(
            ResearchViewState.PARTIAL,
            "Some research components are temporarily unavailable.",
        )
    return ResearchState(
        ResearchViewState.READY,
        "Fresh research snapshot loaded.",
    )


def classify_crypto_state(
    payload: dict[str, Any] | None,
    *,
    error: str | None = None,
) -> ResearchState:
    """Map a general-crypto aggregate to the same stable UI state model."""
    if error:
        return ResearchState(ResearchViewState.ERROR, error)
    if payload is None:
        return ResearchState(
            ResearchViewState.EMPTY,
            "Search for an asset, select its CoinGecko ID, and load research.",
        )
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return ResearchState(
            ResearchViewState.ERROR,
            "The API returned a response without freshness metadata.",
        )
    if meta.get("freshness") == "stale" or meta.get("cache_status") == "stale":
        return ResearchState(
            ResearchViewState.STALE,
            "Showing a stale cached snapshot because CoinGecko refresh failed.",
        )
    if meta.get("partial") is True:
        return ResearchState(
            ResearchViewState.PARTIAL,
            "Some crypto research components are temporarily unavailable.",
        )
    return ResearchState(
        ResearchViewState.READY,
        "Crypto research snapshot loaded.",
    )
