"""Streamlit UI for crypto, Spot, Futures, and PSX-first stock research."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

import streamlit as st

from frontend.client import (
    ResearchApiError,
    delete_stock_price_upload,
    fetch_crypto_research,
    fetch_futures_research,
    fetch_spot_research,
    fetch_stock_price_upload,
    fetch_stock_research,
    list_stock_price_uploads,
    login_user,
    logout_user,
    refresh_user_session,
    search_crypto,
    search_stocks,
    upload_stock_prices,
)
from frontend.research_brief import (
    GUIDED_QUESTIONS,
    answer_stock_question,
    build_stock_research_brief,
)
from frontend.state import (
    ResearchState,
    ResearchViewState,
    classify_crypto_state,
    classify_futures_state,
    classify_research_state,
    classify_stock_state,
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


def _clear_stock_session() -> None:
    for key in (
        "stock_access_token",
        "stock_refresh_token",
        "stock_access_expires_at",
        "stock_refresh_expires_at",
        "stock_user",
        "stock_uploads",
        "stock_private_payload",
    ):
        st.session_state[key] = None


def _store_stock_session(payload: dict[str, Any]) -> None:
    st.session_state.stock_access_token = payload.get("access_token")
    st.session_state.stock_refresh_token = payload.get("refresh_token")
    st.session_state.stock_access_expires_at = payload.get("access_expires_at")
    st.session_state.stock_refresh_expires_at = payload.get("refresh_expires_at")
    st.session_state.stock_user = payload.get("user")


def _stock_access_token(api_url: str) -> str:
    token = st.session_state.stock_access_token
    expires_value = st.session_state.stock_access_expires_at
    try:
        expires_at = datetime.fromisoformat(str(expires_value).replace("Z", "+00:00"))
    except ValueError:
        expires_at = datetime.min.replace(tzinfo=UTC)
    if token and expires_at > datetime.now(UTC) + timedelta(seconds=30):
        return str(token)
    refresh_token = st.session_state.stock_refresh_token
    if not refresh_token:
        _clear_stock_session()
        raise ResearchApiError("Your session expired. Sign in again.")
    try:
        refreshed = refresh_user_session(
            api_base_url=api_url,
            refresh_token=str(refresh_token),
        )
    except ResearchApiError:
        _clear_stock_session()
        raise
    _store_stock_session(refreshed)
    return str(st.session_state.stock_access_token)


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


def _render_futures_research(payload: dict[str, Any]) -> None:
    data = _mapping(payload.get("data"))
    meta = _mapping(payload.get("meta"))
    market = _mapping(data.get("market"))
    analytics = _mapping(data.get("analytics"))
    risk = _mapping(data.get("risk"))

    def percent(value: object) -> str:
        return "Unavailable" if value is None else f"{_number(value)}%"

    st.subheader(f"{data.get('symbol', 'Futures')} perpetual research")
    _status(classify_futures_state(payload))
    st.error(
        data.get(
            "leverage_warning",
            "Leveraged futures can rapidly lose all margin.",
        ),
        icon="⚠️",
    )
    st.caption(
        f"Source: Binance public USD-M endpoints · freshness: "
        f"{meta.get('freshness', 'unknown')} · cache: "
        f"{meta.get('cache_status', 'unknown')} · "
        f"timestamp: {meta.get('source_timestamp', 'unknown')}"
    )
    first, second, third, fourth = st.columns(4)
    first.metric("Mark price", _number(market.get("mark_price")))
    second.metric("Index price", _number(market.get("index_price")))
    third.metric(
        "Funding (annualized)",
        percent(analytics.get("annualized_funding_percent")),
    )
    fourth.metric("Crowding", str(analytics.get("crowding", "unknown")).title())

    funding_tab, oi_tab, positioning_tab, risk_tab = st.tabs(
        ["Funding & basis", "Open interest", "Positioning", "Risk"]
    )
    with funding_tab:
        st.metric(
            "Perpetual basis",
            percent(analytics.get("basis_percent")),
        )
        st.caption(
            f"Next funding (UTC): {market.get('next_funding_time', 'Unavailable')} · "
            f"Observed settlement spacing: "
            f"{_number(analytics.get('observed_funding_interval_hours'))} hours. "
            "Annualization projects the latest historical rate; future rates "
            "may change."
        )
        st.metric(
            "Mark/index premium", percent(analytics.get("mark_index_premium_percent"))
        )
        funding = _mapping(data.get("funding"))
        points = funding.get("points")
        if isinstance(points, list) and points:
            rows = [
                {
                    "time": item["funding_time"],
                    "funding_percent": float(item["funding_rate"]) * 100,
                }
                for item in points
            ]
            st.line_chart(rows, x="time", y="funding_percent")
        else:
            st.info("Funding history is unavailable.")
    with oi_tab:
        open_interest = _mapping(data.get("open_interest"))
        st.metric(
            "Open-interest change",
            percent(analytics.get("open_interest_change_percent")),
        )
        st.caption(
            "Quantity change over "
            f"{_number(analytics.get('open_interest_window_hours'))} hours."
        )
        st.metric(
            "Current open interest (base units)",
            _number(open_interest.get("current_open_interest")),
        )
        history = open_interest.get("history")
        if isinstance(history, list) and history:
            rows = [
                {
                    "time": item["timestamp"],
                    "base_quantity": float(item["open_interest"]),
                }
                for item in history
            ]
            st.line_chart(rows, x="time", y="base_quantity")
        else:
            st.info("Open-interest history is unavailable.")
    with positioning_tab:
        first, second = st.columns(2)
        first.metric("Long accounts", percent(analytics.get("long_account_percent")))
        second.metric(
            "Taker buy share",
            percent(analytics.get("taker_buy_share_percent")),
        )
        anomalies = analytics.get("anomalies")
        if isinstance(anomalies, list) and anomalies:
            st.warning("Detected signals: " + ", ".join(map(str, anomalies)))
        elif analytics.get("crowding") == "unavailable":
            st.info(
                "Positioning evidence is unavailable; no crowding conclusion "
                "can be made."
            )
        else:
            st.info("No rule-based crowding anomaly crossed the configured threshold.")
        st.caption("Account shares count accounts, not capital or position size.")
    with risk_tab:
        _render_risk(risk, title="Deterministic Futures market risk")
        for explanation in risk.get("explanations", []):
            st.caption(f"• {explanation}")

    with st.expander("Freshness warnings and source evidence"):
        st.json(
            {
                "warnings": meta.get("warnings", []),
                "sources": meta.get("sources", []),
                "component_timestamps": data.get("components", {}),
            },
            expanded=False,
        )
    st.caption(data.get("disclaimer", "Research and education only."))
    for limitation in analytics.get("limitations", []):
        st.caption(limitation)


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


def _render_stock_search(payload: dict[str, Any] | None) -> None:
    if payload is None:
        return
    data = _mapping(payload.get("data"))
    license_data = _mapping(data.get("license"))
    results = data.get("results")
    if license_data.get("display_authorized") is not True:
        st.caption(
            "Provider-backed company search is unavailable; enter a known "
            "exchange symbol below."
        )
    if isinstance(results, list) and results:
        st.dataframe(results[:20], use_container_width=True, hide_index=True)


def _render_stock_research(payload: dict[str, Any]) -> None:
    data = _mapping(payload.get("data"))
    meta = _mapping(payload.get("meta"))
    profile = _mapping(data.get("profile"))
    quote = _mapping(data.get("quote"))
    candles = _mapping(data.get("candles"))
    technicals = _mapping(data.get("technicals"))
    risk = _mapping(data.get("risk"))
    fundamentals = _mapping(data.get("fundamentals"))
    fundamental_profile = _mapping(fundamentals.get("profile"))
    fundamental_risk = _mapping(fundamentals.get("risk"))
    fundamental_model = str(fundamentals.get("fundamental_model", "corporate"))
    license_data = _mapping(data.get("license"))

    _status(classify_stock_state(payload))
    st.caption(
        f"Identity: {data.get('exchange', 'PSX')}:{data.get('symbol', 'unknown')} | "
        f"freshness: {meta.get('freshness', 'unknown')} | "
        f"cache: {meta.get('cache_status', 'unknown')}"
    )
    identity = f"{data.get('exchange', 'PSX')}:{data.get('symbol', '?')}"
    company_name = profile.get("company_name") or fundamental_profile.get(
        "company_name"
    )
    st.subheader(f"{company_name} ({identity})" if company_name else identity)
    if data.get("market_data_status") == "unavailable":
        st.info(
            "Current market prices are unavailable because no display-authorized "
            "provider is configured. Official fundamentals and private CSV analysis "
            "remain available independently."
        )
    if quote:
        default_currency = "PKR" if data.get("exchange") == "PSX" else "USD"
        currency = str(quote.get("currency", default_currency))
        change_percent = quote.get("change_percent")
        delta = f"{_number(change_percent)}%" if change_percent is not None else None
        first, second, third, fourth = st.columns(4)
        first.metric(
            f"Latest price ({currency})",
            _number(quote.get("latest_price")),
            delta,
        )
        second.metric("Volume", _number(quote.get("volume"), digits=0))
        third.metric("Day high", _number(quote.get("high")))
        fourth.metric("Day low", _number(quote.get("low")))
    periods = fundamentals.get("periods")
    ratios = fundamentals.get("ratios")
    reports = fundamentals.get("reports")
    if isinstance(periods, list) and periods:
        latest = _mapping(periods[-1])
        st.caption(
            f"Latest reported period: {latest.get('fiscal_period', '?')} "
            f"{latest.get('fiscal_year', '?')} · currency: "
            f"{latest.get('currency', 'unknown')} · basis: "
            f"{latest.get('reporting_basis', 'unknown')} · model: "
            f"{fundamental_model}"
        )
        first, second, third, fourth = st.columns(4)
        if fundamental_model == "bank":
            first.metric("Total income", _number(latest.get("total_income"), digits=0))
            second.metric("Net profit", _number(latest.get("net_income"), digits=0))
            third.metric("Deposits", _number(latest.get("deposits"), digits=0))
            fourth.metric("Equity", _number(latest.get("equity"), digits=0))
        else:
            first.metric("Revenue", _number(latest.get("revenue"), digits=0))
            second.metric("Net profit", _number(latest.get("net_income"), digits=0))
            third.metric("EPS", _number(latest.get("eps")))
            fourth.metric("Equity", _number(latest.get("equity"), digits=0))

    (
        company_tab,
        financial_tab,
        ratio_tab,
        report_tab,
        fundamental_risk_tab,
        market_tab,
        rights_tab,
    ) = st.tabs(
        [
            "Company",
            "Financial performance",
            "Ratios",
            "Reports & announcements",
            "Fundamental risk",
            "Price & technicals",
            "Data sources",
        ]
    )
    with company_tab:
        company = profile or fundamental_profile
        if company:
            st.json(company, expanded=False)
        else:
            st.info("No verified company profile is configured for this identity.")
    with financial_tab:
        if isinstance(periods, list) and periods:
            st.dataframe(periods, use_container_width=True, hide_index=True)
        else:
            st.info(
                "Official financial periods are unavailable. Configure an SEC "
                "source or an operator-verified PSX/SECP/company-report manifest."
            )
    with ratio_tab:
        if isinstance(ratios, list) and ratios:
            st.dataframe(ratios, use_container_width=True, hide_index=True)
        else:
            st.info("Ratios require verified official financial facts.")
    with report_tab:
        if isinstance(reports, list) and reports:
            st.dataframe(reports, use_container_width=True, hide_index=True)
        else:
            st.info("No verified annual, quarterly, or announcement links found.")
    with fundamental_risk_tab:
        _render_risk(fundamental_risk, title="Deterministic fundamental risk")
    with market_tab:
        rows = candles.get("candles")
        if isinstance(rows, list) and rows:
            st.line_chart(rows, x="timestamp", y="close")
            st.dataframe(rows[-30:], use_container_width=True, hide_index=True)
        else:
            st.info(
                "Licensed candles are unavailable. Sign in and use Upload price "
                "history to run private technical analysis."
            )
        if technicals:
            a, b, c, d = st.columns(4)
            a.metric("Trend", str(technicals.get("trend", "unknown")).title())
            b.metric("RSI (14)", _number(technicals.get("rsi_14")))
            c.metric("SMA (20)", _number(technicals.get("sma_20")))
            d.metric(
                "Volatility",
                f"{_number(technicals.get('annualized_volatility_percent'))}%",
            )
            st.json(technicals, expanded=False)
        _render_risk(risk, title="Deterministic stock risk")
    with rights_tab:
        st.markdown(
            "**Four explicit data modes**\n\n"
            "- Licensed provider — current or delayed market research\n"
            "- User supplied — private technical analysis\n"
            "- Official reports — fundamentals and filing research\n"
            "- Offline demo — demonstration only"
        )
        st.json(license_data, expanded=True)
        st.caption(
            "Real-time, delayed, end-of-day, and historical data are separate "
            "license classes. A class remains disabled until its written display "
            "and derived-data scope is recorded."
        )

    with st.expander("Freshness warnings and sources"):
        st.json(
            {"warnings": meta.get("warnings", []), "sources": meta.get("sources", [])}
        )
    st.warning(
        data.get("disclaimer", "Research and education only."),
        icon=":material/info:",
    )
    st.subheader("Evidence assistant")
    st.caption(
        "Bounded, deterministic answers use only the displayed structured facts. "
        "Free-form filing RAG is intentionally deferred until citation evaluation."
    )
    selected_question = st.selectbox(
        "Research question",
        options=list(GUIDED_QUESTIONS),
        format_func=lambda key: GUIDED_QUESTIONS[key],
        key=f"stock_question_{identity}",
    )
    st.markdown(answer_stock_question(payload, selected_question))
    brief = build_stock_research_brief(payload)
    st.download_button(
        "Download source-backed Markdown brief",
        data=brief,
        file_name=f"{identity.replace(':', '-')}-research-brief.md".lower(),
        mime="text/markdown",
        use_container_width=True,
    )


def _render_private_stock_research(payload: dict[str, Any] | None) -> None:
    if payload is None:
        return
    upload = _mapping(payload.get("upload"))
    candles = _mapping(payload.get("candles"))
    technicals = _mapping(payload.get("technicals"))
    trend = _mapping(payload.get("trend"))
    risk = _mapping(payload.get("risk"))
    st.subheader("Private user-supplied price analysis")
    st.caption(
        f"{upload.get('exchange', '?')}:{upload.get('symbol', '?')} · "
        f"{upload.get('row_count', 0)} rows · source: "
        f"{upload.get('source_label', 'user supplied')} · private to owner"
    )
    rows = candles.get("candles")
    if isinstance(rows, list) and rows:
        st.line_chart(rows, x="timestamp", y="close")
    first, second, third, fourth = st.columns(4)
    first.metric("Trend", str(technicals.get("trend", "unknown")).title())
    second.metric("RSI (14)", _number(technicals.get("rsi_14")))
    third.metric("SMA (20)", _number(technicals.get("sma_20")))
    fourth.metric(
        "Volatility",
        f"{_number(technicals.get('annualized_volatility_percent'))}%",
    )
    with st.expander("Technical details"):
        st.json({"technicals": technicals, "trend": trend}, expanded=False)
    _render_risk(risk, title="User-supplied price risk")
    st.warning(
        payload.get(
            "disclaimer",
            "User-supplied data is unverified and is not financial advice.",
        )
    )


for key in (
    "research_payload",
    "research_error",
    "futures_research_payload",
    "futures_research_error",
    "crypto_search_payload",
    "crypto_search_error",
    "crypto_research_payload",
    "crypto_research_error",
    "stock_search_payload",
    "stock_search_error",
    "stock_research_payload",
    "stock_research_error",
    "stock_private_payload",
    "stock_private_error",
    "stock_access_token",
    "stock_refresh_token",
    "stock_access_expires_at",
    "stock_refresh_expires_at",
    "stock_user",
    "stock_uploads",
):
    if key not in st.session_state:
        st.session_state[key] = None

st.title("Investment Research Co-Pilot")

with st.sidebar:
    research_mode = st.radio(
        "Research mode",
        options=["Binance Spot", "Binance Futures", "General crypto", "Stocks"],
        key="research_mode",
    )
    configured_api_url = os.getenv("COPILOT_API_URL", "http://127.0.0.1:8000")
    editable_api_url = (
        os.getenv("COPILOT_ENVIRONMENT", "development") == "development"
        and os.getenv("COPILOT_ALLOW_EDITABLE_API_URL", "false").casefold() == "true"
    )
    if editable_api_url:
        api_url = st.text_input("Development API URL", value=configured_api_url)
    else:
        api_url = configured_api_url
        st.caption("Connected to the deployment-configured research API.")

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
    elif research_mode == "Binance Futures":
        st.header("USD-M Futures inputs")
        futures_symbol = (
            st.text_input("Perpetual symbol", value="BTCUSDT", key="futures_symbol")
            .strip()
            .upper()
        )
        futures_period = st.selectbox(
            "Analysis period",
            options=["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"],
            index=3,
        )
        st.warning(
            "Futures are leveraged instruments. This page does not connect an "
            "account or place trades."
        )
        if st.button("Load Futures research", type="primary", use_container_width=True):
            with st.spinner(
                "Loading public mark price, funding, open interest, basis, "
                "and positioning…"
            ):
                try:
                    st.session_state.futures_research_payload = fetch_futures_research(
                        api_base_url=api_url,
                        symbol=futures_symbol,
                        period=futures_period,
                    )
                    st.session_state.futures_research_error = None
                except ResearchApiError as error:
                    st.session_state.futures_research_payload = None
                    st.session_state.futures_research_error = str(error)
    elif research_mode == "General crypto":
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
    else:
        st.header("Stock identity")
        stock_exchange = st.selectbox(
            "Exchange",
            options=["PSX", "NASDAQ", "NYSE"],
            index=0,
            help="PSX is the default for Pakistan; the data model is exchange-neutral.",
        )
        stock_query = st.text_input(
            "Provider company search (optional)",
            value="OGDC",
            help="This activates after a display-authorized provider is configured.",
        )
        run_stock_search = st.button("Search stocks", use_container_width=True)
        if run_stock_search:
            with st.spinner("Searching exchange-qualified stock identities..."):
                try:
                    st.session_state.stock_search_payload = search_stocks(
                        api_base_url=api_url,
                        query=stock_query,
                        exchange=stock_exchange,
                    )
                    st.session_state.stock_search_error = None
                except ResearchApiError as error:
                    st.session_state.stock_search_payload = None
                    st.session_state.stock_search_error = str(error)
        stock_symbol = (
            st.text_input("Selected stock symbol", value="OGDC").strip().upper()
        )
        stock_interval = st.selectbox(
            "Stock candle interval",
            options=["1d", "1w"],
            index=0,
        )
        stock_days = st.select_slider(
            "Stock history range (days)",
            options=[30, 90, 180, 365, 730, 1825],
            value=365,
        )
        load_stock = st.button(
            "Load stock research", type="primary", use_container_width=True
        )
        if load_stock:
            with st.spinner("Loading licensed or unavailable stock snapshot..."):
                try:
                    st.session_state.stock_research_payload = fetch_stock_research(
                        api_base_url=api_url,
                        exchange=stock_exchange,
                        symbol=stock_symbol,
                        interval=stock_interval,
                        days=stock_days,
                    )
                    st.session_state.stock_research_error = None
                except ResearchApiError as error:
                    st.session_state.stock_research_payload = None
                    st.session_state.stock_research_error = str(error)

        st.divider()
        st.subheader("Private price history")
        if st.session_state.stock_access_token is None:
            login_email = st.text_input("Account email", key="stock_login_email")
            login_password = st.text_input(
                "Password", type="password", key="stock_login_password"
            )
            if st.button("Sign in for private uploads", use_container_width=True):
                try:
                    login_payload = login_user(
                        api_base_url=api_url,
                        email=login_email,
                        password=login_password,
                    )
                    _store_stock_session(login_payload)
                    st.session_state.stock_private_error = None
                except ResearchApiError as error:
                    st.session_state.stock_private_error = str(error)
        else:
            user = _mapping(st.session_state.stock_user)
            st.caption(
                f"Signed in as {user.get('email', 'user')} until "
                f"{st.session_state.stock_access_expires_at or 'token expiry'}"
            )
            if st.button("Sign out of uploads", use_container_width=True):
                logout_error: str | None = None
                refresh_token = st.session_state.stock_refresh_token
                if refresh_token:
                    try:
                        logout_user(
                            api_base_url=api_url,
                            refresh_token=str(refresh_token),
                        )
                    except ResearchApiError as error:
                        logout_error = (
                            f"Local session cleared; server logout could not be "
                            f"confirmed: {error}"
                        )
                _clear_stock_session()
                st.session_state.stock_private_error = logout_error

            if st.button("Refresh my uploads", use_container_width=True):
                try:
                    access_token = _stock_access_token(api_url)
                    st.session_state.stock_uploads = list_stock_price_uploads(
                        api_base_url=api_url,
                        access_token=access_token,
                        exchange=stock_exchange,
                        symbol=stock_symbol,
                    )
                    st.session_state.stock_private_error = None
                except ResearchApiError as error:
                    st.session_state.stock_private_error = str(error)

            uploads = st.session_state.stock_uploads
            if isinstance(uploads, list) and uploads:
                labels = {
                    str(item.get("upload_id")): (
                        f"{item.get('source_label', 'upload')} · "
                        f"{item.get('data_start', '?')} to {item.get('data_end', '?')}"
                    )
                    for item in uploads
                    if isinstance(item, dict) and item.get("upload_id")
                }
                selected_upload = st.selectbox(
                    "Saved private histories",
                    options=list(labels),
                    format_func=lambda upload_id: labels[upload_id],
                )
                load_saved, delete_saved = st.columns(2)
                if load_saved.button("Open", use_container_width=True):
                    try:
                        st.session_state.stock_private_payload = (
                            fetch_stock_price_upload(
                                api_base_url=api_url,
                                access_token=_stock_access_token(api_url),
                                exchange=stock_exchange,
                                symbol=stock_symbol,
                                upload_id=selected_upload,
                            )
                        )
                    except ResearchApiError as error:
                        st.session_state.stock_private_error = str(error)
                if delete_saved.button("Delete", use_container_width=True):
                    try:
                        delete_stock_price_upload(
                            api_base_url=api_url,
                            access_token=_stock_access_token(api_url),
                            exchange=stock_exchange,
                            symbol=stock_symbol,
                            upload_id=selected_upload,
                        )
                        st.session_state.stock_uploads = None
                        st.session_state.stock_private_payload = None
                    except ResearchApiError as error:
                        st.session_state.stock_private_error = str(error)

        csv_file = st.file_uploader(
            "Upload price history",
            type=["csv"],
            help="Required columns: date,open,high,low,close,volume; 20-1,500 rows.",
        )
        upload_source = st.text_input(
            "Price data source",
            value="Legally obtained user data",
            help="Record where and when you obtained this private dataset.",
        )
        upload_source_date = st.date_input("Source date", value=date.today())
        upload_currency = st.selectbox("CSV currency", options=["PKR", "USD"], index=0)
        can_upload = (
            csv_file is not None and st.session_state.stock_access_token is not None
        )
        if st.button(
            "Analyze uploaded prices",
            type="primary",
            use_container_width=True,
            disabled=not can_upload,
        ):
            try:
                if csv_file is None:
                    raise ResearchApiError("Select a CSV file first.")
                st.session_state.stock_private_payload = upload_stock_prices(
                    api_base_url=api_url,
                    access_token=_stock_access_token(api_url),
                    exchange=stock_exchange,
                    symbol=stock_symbol,
                    filename=csv_file.name,
                    csv_bytes=csv_file.getvalue(),
                    source_label=upload_source,
                    source_date=upload_source_date,
                    currency=upload_currency,
                )
                st.session_state.stock_uploads = list_stock_price_uploads(
                    api_base_url=api_url,
                    access_token=_stock_access_token(api_url),
                    exchange=stock_exchange,
                    symbol=stock_symbol,
                )
                st.session_state.stock_private_error = None
            except ResearchApiError as error:
                st.session_state.stock_private_payload = None
                st.session_state.stock_private_error = str(error)

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
elif research_mode == "Binance Futures":
    st.write(
        "Free, public, read-only USD-M perpetual research. No API key, account, "
        "orders, or trading controls are used."
    )
    futures_state = classify_futures_state(
        st.session_state.futures_research_payload,
        error=st.session_state.futures_research_error,
    )
    if futures_state.state in {ResearchViewState.EMPTY, ResearchViewState.ERROR}:
        _status(futures_state)
    else:
        _render_futures_research(st.session_state.futures_research_payload)
elif research_mode == "General crypto":
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
else:
    st.write(
        "Exchange-qualified stock research with PSX as the default selection, "
        "without making the architecture PSX-only."
    )
    if st.session_state.stock_search_error:
        st.error(st.session_state.stock_search_error, icon=":material/error:")
    _render_stock_search(st.session_state.stock_search_payload)
    stock_state = classify_stock_state(
        st.session_state.stock_research_payload,
        error=st.session_state.stock_research_error,
    )
    if stock_state.state in {ResearchViewState.EMPTY, ResearchViewState.ERROR}:
        _status(stock_state)
    else:
        _render_stock_research(st.session_state.stock_research_payload)
    if st.session_state.stock_private_error:
        st.error(st.session_state.stock_private_error, icon=":material/error:")
    _render_private_stock_research(st.session_state.stock_private_payload)
