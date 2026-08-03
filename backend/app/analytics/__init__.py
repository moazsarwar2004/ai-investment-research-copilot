"""Deterministic analytics that never perform provider or database I/O."""

from backend.app.analytics.binance_spot import (
    OrderBookAnalysis,
    SpotRisk,
    TechnicalAnalysis,
    TradeAnalysis,
    analyze_order_book,
    analyze_technicals,
    analyze_trades,
    build_spot_risk,
)

__all__ = [
    "OrderBookAnalysis",
    "SpotRisk",
    "TechnicalAnalysis",
    "TradeAnalysis",
    "analyze_order_book",
    "analyze_technicals",
    "analyze_trades",
    "build_spot_risk",
]
