"""First end-user Binance Spot research page."""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

from frontend.client import ResearchApiError, fetch_spot_research
from frontend.state import ResearchViewState, classify_research_state

st.set_page_config(
    page_title="Binance Spot Research",
    page_icon="📊",
    layout="wide",
)


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: object, *, digits: int = 2) -> str:
    try:
        return f"{float(str(value)):,.{digits}f}"
    except (TypeError, ValueError):
        return "Unavailable"


def _render_research(payload: dict[str, Any]) -> None:
    data = _mapping(payload.get("data"))
    meta = _mapping(payload.get("meta"))
    ticker = _mapping(data.get("ticker"))
    technicals = _mapping(data.get("technicals"))
    risk = _mapping(data.get("risk"))

    state = classify_research_state(payload)
    if state.state is ResearchViewState.STALE:
        st.warning(state.message, icon="⚠️")
    elif state.state is ResearchViewState.PARTIAL:
        st.warning(state.message, icon="🧩")
    else:
        st.success(state.message, icon="✅")

    st.caption(
        f"Source: Binance · freshness: {meta.get('freshness', 'unknown')} · "
        f"cache: {meta.get('cache_status', 'unknown')} · "
        f"staleness: {meta.get('staleness_seconds', 'unknown')}s"
    )

    st.subheader(f"{data.get('symbol', 'Spot pair')} market snapshot")
    first, second, third, fourth = st.columns(4)
    first.metric(
        "Last price",
        _number(ticker.get("last_price"), digits=8),
        f"{_number(ticker.get('price_change_percent'))}%",
    )
    second.metric(
        "24h high / low",
        f"{_number(ticker.get('high_price'), digits=8)} / "
        f"{_number(ticker.get('low_price'), digits=8)}",
    )
    third.metric("24h quote volume", _number(ticker.get("quote_volume")))
    fourth.metric("24h trades", _number(ticker.get("trade_count"), digits=0))

    chart_tab, technical_tab, liquidity_tab, trades_tab, risk_tab = st.tabs(
        ["Price", "Technicals", "Liquidity", "Trades", "Risk"]
    )
    with chart_tab:
        candles = _mapping(data.get("candles")).get("candles")
        if isinstance(candles, list) and candles:
            chart_rows = [
                {
                    "time": item.get("close_time"),
                    "close": float(str(item.get("close"))),
                }
                for item in candles
                if isinstance(item, dict) and item.get("close") is not None
            ]
            st.line_chart(chart_rows, x="time", y="close")
            st.dataframe(candles[-20:], use_container_width=True, hide_index=True)
        else:
            st.info("Candle data is unavailable for this snapshot.")

    with technical_tab:
        if technicals:
            a, b, c, d = st.columns(4)
            a.metric("Trend", str(technicals.get("trend", "Unavailable")).title())
            b.metric("RSI (14)", _number(technicals.get("rsi_14")))
            c.metric("SMA (20)", _number(technicals.get("sma_20"), digits=8))
            d.metric(
                "Annualized volatility",
                f"{_number(technicals.get('annualized_volatility_percent'))}%",
            )
            st.json(technicals, expanded=False)
        else:
            st.info("Technical indicators are unavailable.")

    with liquidity_tab:
        order_book = _mapping(data.get("order_book"))
        if order_book:
            a, b, c, d = st.columns(4)
            a.metric("Spread (bps)", _number(order_book.get("spread_bps")))
            b.metric("Imbalance", _number(order_book.get("imbalance"), digits=4))
            c.metric(
                "Buy slippage (bps)",
                _number(order_book.get("estimated_buy_slippage_bps")),
            )
            d.metric("Pressure", str(order_book.get("pressure", "unknown")).title())
            bids, asks = st.columns(2)
            bids.dataframe(
                order_book.get("bids", []),
                use_container_width=True,
                hide_index=True,
            )
            asks.dataframe(
                order_book.get("asks", []),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Order-book analytics are unavailable.")

    with trades_tab:
        trades = _mapping(data.get("trades"))
        if trades:
            a, b, c = st.columns(3)
            a.metric("Pressure", str(trades.get("pressure", "unknown")).title())
            b.metric("Buy pressure", _number(trades.get("buy_pressure"), digits=4))
            c.metric("Large trades", _number(trades.get("large_trade_count"), digits=0))
            st.dataframe(
                trades.get("trades", []),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Recent public trades are unavailable.")

    with risk_tab:
        if risk:
            label = str(risk.get("risk_label", "unknown")).title()
            st.metric(
                "Deterministic Spot risk",
                _number(risk.get("overall_score")),
                label,
            )
            st.progress(float(risk.get("overall_score", 0)) / 100)
            components = _mapping(risk.get("component_scores"))
            st.bar_chart(
                [
                    {"component": key, "score": value}
                    for key, value in components.items()
                ],
                x="component",
                y="score",
            )
            st.caption(
                f"Method: {risk.get('methodology_version', 'unknown')} · "
                f"data confidence: {_number(risk.get('data_confidence'))}"
            )
            for limitation in risk.get("limitations", []):
                st.caption(f"• {limitation}")
        else:
            st.info("Risk analytics are unavailable.")

    with st.expander("Freshness warnings and sources"):
        st.json(
            {
                "warnings": meta.get("warnings", []),
                "sources": meta.get("sources", []),
            }
        )

    st.warning(
        data.get("disclaimer", "Research and education only."),
        icon=":material/info:",
    )


st.title("Binance Spot Research")
st.write(
    "Public, read-only market research with deterministic technical, liquidity, "
    "trade-pressure, and risk analytics."
)

with st.sidebar:
    st.header("Research inputs")
    api_url = st.text_input(
        "API URL",
        value=os.getenv("COPILOT_API_URL", "http://127.0.0.1:8000"),
    )
    symbol = st.text_input("Spot pair", value="BTCUSDT").strip().upper()
    interval = st.selectbox(
        "Candle interval",
        options=["1m", "5m", "15m", "1h", "4h", "1d", "1w"],
        index=3,
    )
    slippage_notional = st.number_input(
        "Slippage notional (quote asset)",
        min_value=1.0,
        max_value=1_000_000.0,
        value=1_000.0,
        step=100.0,
    )
    load = st.button("Load research", type="primary", use_container_width=True)

if "research_payload" not in st.session_state:
    st.session_state.research_payload = None
if "research_error" not in st.session_state:
    st.session_state.research_error = None

if load:
    with st.spinner("Loading Binance ticker, candles, depth, and trades…"):
        try:
            st.session_state.research_payload = fetch_spot_research(
                api_base_url=api_url,
                symbol=symbol,
                interval=interval,
                slippage_notional_quote=slippage_notional,
            )
            st.session_state.research_error = None
        except ResearchApiError as error:
            st.session_state.research_payload = None
            st.session_state.research_error = str(error)

view_state = classify_research_state(
    st.session_state.research_payload,
    error=st.session_state.research_error,
)
if view_state.state is ResearchViewState.EMPTY:
    st.info(view_state.message)
elif view_state.state is ResearchViewState.ERROR:
    st.error(view_state.message, icon="🚫")
else:
    _render_research(st.session_state.research_payload)
