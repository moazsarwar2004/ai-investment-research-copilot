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
from backend.app.analytics.crypto import (
    CryptoAnomalyAnalysis,
    CryptoAnomalyEvent,
    CryptoRisk,
    CryptoTechnicalAnalysis,
    CryptoTrendAnalysis,
    analyze_crypto_anomalies,
    analyze_crypto_technicals,
    build_crypto_risk,
    build_crypto_trend,
)

__all__ = [
    "CryptoAnomalyAnalysis",
    "CryptoAnomalyEvent",
    "CryptoRisk",
    "CryptoTechnicalAnalysis",
    "CryptoTrendAnalysis",
    "OrderBookAnalysis",
    "SpotRisk",
    "TechnicalAnalysis",
    "TradeAnalysis",
    "analyze_crypto_anomalies",
    "analyze_crypto_technicals",
    "analyze_order_book",
    "analyze_technicals",
    "analyze_trades",
    "build_crypto_risk",
    "build_crypto_trend",
    "build_spot_risk",
]
