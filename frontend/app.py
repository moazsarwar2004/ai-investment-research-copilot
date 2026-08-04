"""Streamlit research UI for Binance Spot and general cryptocurrency data."""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

from frontend.client import (
    ResearchApiError,
    fetch_crypto_research,
    fetch_spot_research,
    search_crypto,
)
from frontend.state import (
    ResearchState,
    ResearchViewState,
    classify_crypto_state,
    classify_research_state,
)

st.set_page_config(
    page_title="Investment Research Co-Pilot",
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


def _status(state: ResearchState) -> None:
    if state.state is ResearchViewState.STALE:
        st.warning(state.message, icon="⚠️")
    elif state.state is ResearchViewState.PARTIAL:
        st.warning(state.message, icon="🧩")
    elif state.state is ResearchViewState.ERROR:
        st.error(state.message, icon="🚫")
    elif state.state is ResearchViewState.EMPTY:
        st.info(state.message)
    else:
        st.success(state.message, icon="✅")


def _render_risk(risk: dict[str, Any], *, title: str) -> None:
    if not risk:
        st.info("Risk analytics are unavailable.")
        return
    label = str(risk.get("risk_label", "unknown")).title()
    score = min(100.0, max(0.0, float(str(risk.get("overall_score", 0)))))
    st.metric(title, _number(score), label)
    st.progress(score / 100)
    components = _mapping(risk.get("component_scores"))
    if components:
        st.bar_chart(
            [{"component": key, "score": value} for key, value in components.items()],
            x="component",
            y="score",
        )
    st.caption(
        f"Method: {risk.get('methodology_version', 'unknown')} · "
        f"data confidence: {_number(risk.get('data_confidence'))}"
    )
    missing = risk.get("missing_inputs", [])
    if isinstance(missing, list) and missing:
        st.caption(f"Missing inputs: {', '.join(str(item) for item in missing)}")
    for limitation in risk.get("limitations", []):
        st.caption(f"• {limitation}")


def _render_spot_research(payload: dict[str, Any]) -> None:
    data = _mapping(payload.get("data"))
    meta = _mapping(payload.get("meta"))
    ticker = _mapping(data.get("ticker"))
    technicals = _mapping(data.get("technicals"))
    risk = _mapping(data.get("risk"))

    _status(classify_research_state(payload))
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
                order_book.get("bids", []), use_container_width=True, hide_index=True
            )
            asks.dataframe(
                order_book.get("asks", []), use_container_width=True, hide_index=True
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
                trades.get("trades", []), use_container_width=True, hide_index=True
            )
        else:
            st.info("Recent public trades are unavailable.")

    with risk_tab:
        _render_risk(risk, title="Deterministic Spot risk")

    with st.expander("Freshness warnings and sources"):
        st.json(
            {"warnings": meta.get("warnings", []), "sources": meta.get("sources", [])}
        )
    st.warning(
        data.get("disclaimer", "Research and education only."),
        icon=":material/info:",
    )


def _crypto_choices(payload: dict[str, Any] | None) -> list[tuple[str, str]]:
    coins = _mapping(_mapping(payload).get("data")).get("coins")
    if not isinstance(coins, list) or not coins:
        return [
            ("Bitcoin (BTC) — bitcoin", "bitcoin"),
            ("Ethereum (ETH) — ethereum", "ethereum"),
        ]
    choices: list[tuple[str, str]] = []
    for item in coins:
        if not isinstance(item, dict) or not isinstance(item.get("coin_id"), str):
            continue
        rank = item.get("market_cap_rank")
        rank_text = f" · rank {rank}" if rank is not None else ""
        choices.append(
            (
                f"{item.get('name', item['coin_id'])} "
                f"({item.get('symbol', '?')}) — {item['coin_id']}{rank_text}",
                item["coin_id"],
            )
        )
    return choices or [("Bitcoin (BTC) — bitcoin", "bitcoin")]


def _render_crypto_search(payload: dict[str, Any] | None) -> None:
    if payload is None:
        return
    data = _mapping(payload.get("data"))
    resolution = _mapping(data.get("resolution"))
    coins = data.get("coins")
    if resolution.get("ambiguous_symbol") is True:
        st.warning(str(resolution.get("message", "The symbol is ambiguous.")))
    else:
        st.caption(str(resolution.get("message", "Select a provider ID.")))
    if isinstance(coins, list):
        st.dataframe(coins[:20], use_container_width=True, hide_index=True)


def _render_crypto_research(payload: dict[str, Any]) -> None:
    data = _mapping(payload.get("data"))
    meta = _mapping(payload.get("meta"))
    overview = _mapping(data.get("overview"))
    technicals = _mapping(data.get("technicals"))
    anomalies = _mapping(data.get("anomalies"))
    risk = _mapping(data.get("risk"))

    _status(classify_crypto_state(payload))
    st.markdown("**Powered by CoinGecko**")
    st.caption(
        f"Provider ID: {data.get('coin_id', 'unknown')} · "
        f"freshness: {meta.get('freshness', 'unknown')} · "
        f"cache: {meta.get('cache_status', 'unknown')} · "
        f"staleness: {meta.get('staleness_seconds', 'unknown')}s"
    )

    st.subheader(
        f"{overview.get('name', data.get('coin_id', 'Crypto asset'))} "
        f"({overview.get('symbol', '?')})"
    )
    first, second, third, fourth = st.columns(4)
    first.metric(
        "Price (USD)",
        _number(overview.get("current_price"), digits=8),
        f"{_number(overview.get('price_change_percentage_24h'))}%",
    )
    second.metric("Market-cap rank", _number(overview.get("market_cap_rank"), digits=0))
    third.metric("Market cap", f"${_number(overview.get('market_cap'))}")
    fourth.metric("24h volume", f"${_number(overview.get('total_volume_24h'))}")

    history_tab, technical_tab, anomaly_tab, supply_tab, risk_tab = st.tabs(
        ["History", "Technicals", "Anomalies", "Market & supply", "Risk"]
    )
    with history_tab:
        points = _mapping(data.get("history")).get("points")
        if isinstance(points, list) and points:
            st.line_chart(points, x="timestamp", y="price")
            st.dataframe(points[-30:], use_container_width=True, hide_index=True)
        else:
            st.info("Historical price data is unavailable for this snapshot.")

    with technical_tab:
        if technicals:
            a, b, c, d = st.columns(4)
            a.metric("Trend", str(technicals.get("trend", "unknown")).title())
            b.metric("RSI (14)", _number(technicals.get("rsi_14")))
            c.metric(
                "Volatility",
                f"{_number(technicals.get('annualized_volatility_percent'))}%",
            )
            d.metric(
                "Maximum drawdown",
                f"{_number(technicals.get('maximum_drawdown_percent'))}%",
            )
            st.json(technicals, expanded=False)
        else:
            st.info("Technical indicators are unavailable.")

    with anomaly_tab:
        if anomalies:
            a, b, c = st.columns(3)
            a.metric("Status", str(anomalies.get("status", "unknown")).title())
            b.metric("Anomaly score", _number(anomalies.get("anomaly_score")))
            c.metric("Events", len(anomalies.get("events", [])))
            st.dataframe(
                anomalies.get("events", []), use_container_width=True, hide_index=True
            )
        else:
            st.info("Anomaly analysis is unavailable.")

    with supply_tab:
        a, b, c, d = st.columns(4)
        a.metric("Circulating supply", _number(overview.get("circulating_supply")))
        b.metric("Total supply", _number(overview.get("total_supply")))
        c.metric("Max supply", _number(overview.get("max_supply")))
        d.metric(
            "Distance from ATH",
            f"{_number(overview.get('distance_from_ath_percent'))}%",
        )
        st.json(overview, expanded=False)

    with risk_tab:
        _render_risk(risk, title="Deterministic crypto risk")

    with st.expander("Freshness warnings and sources"):
        st.json(
            {"warnings": meta.get("warnings", []), "sources": meta.get("sources", [])}
        )
    st.warning(
        data.get("disclaimer", "Research and education only."),
        icon=":material/info:",
    )


for key in (
    "research_payload",
    "research_error",
    "crypto_search_payload",
    "crypto_search_error",
    "crypto_research_payload",
    "crypto_research_error",
):
    if key not in st.session_state:
        st.session_state[key] = None

st.title("Investment Research Co-Pilot")

with st.sidebar:
    research_mode = st.radio(
        "Research mode",
        options=["Binance Spot", "General crypto"],
        key="research_mode",
    )
    api_url = st.text_input(
        "API URL",
        value=os.getenv("COPILOT_API_URL", "http://127.0.0.1:8000"),
    )

    if research_mode == "Binance Spot":
        st.header("Spot inputs")
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
        load_spot = st.button(
            "Load Spot research", type="primary", use_container_width=True
        )
        if load_spot:
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
    else:
        st.header("Crypto identity")
        search_query = st.text_input("Name, symbol, or CoinGecko ID", value="bitcoin")
        run_search = st.button("Search CoinGecko", use_container_width=True)
        if run_search:
            with st.spinner("Searching CoinGecko identities…"):
                try:
                    st.session_state.crypto_search_payload = search_crypto(
                        api_base_url=api_url,
                        query=search_query,
                    )
                    st.session_state.crypto_search_error = None
                except ResearchApiError as error:
                    st.session_state.crypto_search_payload = None
                    st.session_state.crypto_search_error = str(error)
        choices = _crypto_choices(st.session_state.crypto_search_payload)
        choice_labels = {coin_id: label for label, coin_id in choices}
        selected_coin_id = st.selectbox(
            "CoinGecko provider ID",
            options=list(choice_labels),
            format_func=lambda value: choice_labels[value],
        )
        history_days = st.select_slider(
            "History range (days)",
            options=[1, 7, 30, 90, 365],
            value=90,
        )
        load_crypto = st.button(
            "Load crypto research", type="primary", use_container_width=True
        )
        if load_crypto:
            with st.spinner("Loading CoinGecko market data and history…"):
                try:
                    st.session_state.crypto_research_payload = fetch_crypto_research(
                        api_base_url=api_url,
                        coin_id=selected_coin_id,
                        days=history_days,
                    )
                    st.session_state.crypto_research_error = None
                except ResearchApiError as error:
                    st.session_state.crypto_research_payload = None
                    st.session_state.crypto_research_error = str(error)

if research_mode == "Binance Spot":
    st.write(
        "Public, read-only Spot research with deterministic technical, liquidity, "
        "trade-pressure, and risk analytics."
    )
    spot_state = classify_research_state(
        st.session_state.research_payload,
        error=st.session_state.research_error,
    )
    if spot_state.state in {ResearchViewState.EMPTY, ResearchViewState.ERROR}:
        _status(spot_state)
    else:
        _render_spot_research(st.session_state.research_payload)
else:
    st.write(
        "General cryptocurrency research uses canonical CoinGecko IDs, "
        "provider-attributed market history, and deterministic analytics."
    )
    if st.session_state.crypto_search_error:
        st.error(st.session_state.crypto_search_error, icon="🚫")
    _render_crypto_search(st.session_state.crypto_search_payload)
    crypto_state = classify_crypto_state(
        st.session_state.crypto_research_payload,
        error=st.session_state.crypto_research_error,
    )
    if crypto_state.state in {ResearchViewState.EMPTY, ResearchViewState.ERROR}:
        _status(crypto_state)
    else:
        _render_crypto_research(st.session_state.crypto_research_payload)
