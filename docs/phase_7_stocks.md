# Phase 7 — Exchange-neutral stock research

## 1. Outcome

Phase 7 adds an exchange-qualified stock research surface without selecting an
unlicensed market-data feed. PSX is the default selection in the Streamlit UI
for the Pakistan-based pilot, but the backend contract is not PSX-only.

Implemented:

- Explicit `PSX`, `NASDAQ`, and `NYSE` exchange identities, preventing a ticker
  from being treated as globally unique.
- Provider-neutral search, profile, quote, and candle contracts.
- A hard activation gate requiring provider, plan, terms URL, review date,
  display authorization, delay, and attribution metadata.
- Structured `freshness: unavailable`, `partial: true` responses when no
  display-authorized provider is configured.
- Daily and weekly candle bounds plus deterministic stock technicals, trend,
  and price/volume risk.
- Seven read-only FastAPI routes and a Stocks Streamlit mode with PSX selected
  by default.
- Dated synthetic/offline tests. Normal tests never call PSX, a stock vendor,
  SEC EDGAR, or any other live source.

Canonical stock identity is `exchange:symbol`, such as `PSX:OGDC`,
`NASDAQ:AAPL`, or `NYSE:KO`. The API retains the planned `/stocks/{symbol}`
paths and takes `exchange` as an explicit query parameter; it defaults to `PSX`
only as a product convenience.

## 2. Market-data rights review

Reviewed on 2026-08-04:

- [PSX Data Services & Vending](https://www.psx.com.pk/psx/product-and-services/data-services-vending)
  says displaying or disseminating PSX live or delayed prices, bids/asks,
  volumes, indices, and related market data through websites or applications
  requires the applicable PSX rights/license. PSX offers real-time levels,
  end-of-day, historical, and corporate-announcement products. Authorization
  requests go to `marketdatarequest@psx.com.pk`.
- [Twelve Data usage rights](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage)
  says individual plans are for personal/internal use and do not permit
  redistribution or commercial display to third parties. Business and
  exchange-specific approval may still be required.
- [Twelve Data U.S. equities guidance](https://support.twelvedata.com/en/articles/9935903-us-equities-market-data)
  describes paid/add-on paths for external distribution and display; this does
  not establish a free external-display entitlement for the pilot.
- [Alpaca redistribution guidance](https://alpaca.markets/support/redistribute-alpaca-api)
  says Alpaca API data cannot be redistributed.
- [Alpha Vantage plans](https://www.alphavantage.co/premium/) do not document a
  reviewed free entitlement suitable for this multi-user display model.

Decision: no live adapter is selected. Scraping PSX, Yahoo, Nasdaq, or another
site is prohibited. Phase 7 is complete only in its documented unavailable
mode; quote availability remains an external release gate.

## 3. License gate

`StockMarketDataProvider` cannot be activated unless its immutable
`StockProviderLicense` records:

| Field | Purpose |
| --- | --- |
| Provider and plan | Identifies the exact commercial/data product |
| Terms URL and review date | Makes the decision auditable and recheckable |
| `display_authorized` | Hard gate; must be true |
| Quote delay | Prevents the UI from implying real-time data |
| Attribution | Required source wording retained with displayed data |

Without that record, every stock route is still available but returns null
price-dependent components, `source: unavailable`, `freshness: unavailable`, a
stable warning, and the research disclaimer. It never substitutes zeros or
silently serves a fixture as current data.

## 4. Public API

All paths are below `/api/v1`. `exchange` accepts `PSX`, `NASDAQ`, or `NYSE` and
defaults to `PSX`.

| Route | Result |
| --- | --- |
| `GET /stocks/search?q=&exchange=` | Exchange-scoped identity candidates, or an empty licensed-gate response |
| `GET /stocks/{symbol}?exchange=` | Profile plus quote, independently nullable |
| `GET /stocks/{symbol}/candles` | Daily/weekly OHLCV for an allowed range |
| `GET /stocks/{symbol}/technicals` | Deterministic indicator set |
| `GET /stocks/{symbol}/trend` | Rule classification with evidence |
| `GET /stocks/{symbol}/risk` | Renormalized price/volume risk |
| `GET /stocks/{symbol}/research` | Partial-tolerant aggregate for the UI |

Supported history ranges are 30, 90, 180, 365, 730, and 1,825 days. Symbols
are uppercase, bounded, and may contain one class suffix such as `BRK.B`.

## 5. Deterministic analytics

`stock-technicals-v1` calculates:

- SMA(20/50/200) and EMA(12/26).
- RSI(14), MACD/signal/histogram, and Bollinger Bands(20, 2σ).
- ATR(14), ROC(20), and 20-period momentum.
- Interval-aware annualized historical volatility and maximum drawdown.
- 20-period support/resistance and a reproducible trend/confidence rule.

`stock-risk-v1` uses volatility (35%), drawdown (25%), trend instability (20%),
and liquidity (20%). Missing components are removed and remaining weights are
renormalized. Coverage and stale freshness lower `data_confidence`. SEC/SECP
fundamental risk remains outside this phase.

## 6. Exit-gate evidence

| Required scenario | Evidence |
| --- | --- |
| External-display license recorded or quote unavailable | Default route/API/UI tests assert null quote/candles plus `freshness: unavailable` |
| Provider abstraction | Abstract async search/profile/quote/candles interface with immutable license metadata |
| Exchange neutrality | PSX default and explicit NASDAQ request use the same route/service contract |
| PSX-aware product | PSX is the UI default; currency is provider-normalized and supports PKR |
| Technicals | Golden 220-candle test covers long-horizon and volatility/drawdown indicators |
| Risk | Complete and missing-liquidity tests verify weight renormalization |
| SEC independence | All stock tests run without database, SEC, or external provider access |
| UI states | Empty, unavailable/partial, stale, error, and fixture-render tests |

Focused verification:

```powershell
python -m pytest -q `
  backend/app/tests/test_stock_analytics.py `
  backend/app/tests/test_stock_service.py `
  backend/app/tests/test_stock_api.py `
  backend/app/tests/test_frontend_state.py
```

## 7. Demo

Start the API, then request the default Pakistan-focused identity:

```powershell
Invoke-RestMethod `
  'http://127.0.0.1:8000/api/v1/stocks/OGDC/research?exchange=PSX&days=365'
```

Expected until a licensed provider is configured:

```text
data.exchange              PSX
data.symbol                OGDC
data.quote                 null
data.candles               null
data.market_data_status    unavailable
meta.freshness             unavailable
meta.partial               true
```

The same contract supports `exchange=NASDAQ&symbol=AAPL` without a separate
U.S.-only API.

## 8. Common errors

| Symptom | Meaning / correction |
| --- | --- |
| `422` for a stock path | Use an uppercase symbol such as `OGDC`, `AAPL`, or `BRK.B` |
| `422` for `exchange` | Phase 7 exposes `PSX`, `NASDAQ`, and `NYSE` |
| Unavailable banner | No reviewed external-display license is configured; this is expected |
| Missing SMA(200) | The selected licensed history contains fewer than 200 candles |
| Partial risk | Quote/liquidity or candle technicals are missing; weights were renormalized |
| Stale badge | A licensed refresh failed and a still-permitted cached snapshot is shown |

## 9. Checklist

- [x] Exchange-qualified identity; PSX is a default, not an architectural lock.
- [x] Current PSX and provider display-rights review.
- [x] Hard immutable license metadata gate.
- [x] Search/profile/quote/candle provider abstraction.
- [x] Structured unavailable responses with no fabricated values.
- [x] Daily/weekly range and symbol validation.
- [x] Full Phase 7 deterministic technical set.
- [x] Explainable price/volume risk with missing-input renormalization.
- [x] Seven read-only routes and a partial-tolerant aggregate.
- [x] Stock Streamlit mode with PSX selected by default.
- [x] Provider, analytics, service, API, and UI tests.
- [x] No live stock or SEC dependency in normal tests.

Recommended phase-completion commit:

```text
feat: complete phase 7 exchange-neutral stock research
```

## 10. Phase 8 boundary

Phase 8 retains SEC/EDGAR support for U.S. securities. Pakistan-focused
fundamentals and disclosures should be added as a separate PSX/SECP source
within the same regulatory-data boundary; Phase 7 does not rename or replace
the existing SEC plan.
