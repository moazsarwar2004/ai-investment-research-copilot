# Data Sources and Provider Policy

Verification date: 2026-07-13. See [free_resource_verification.md](free_resource_verification.md) for official evidence and limits.

## 1. Selection principles

1. Use documented APIs, not scraped web pages or unofficial endpoints.
2. Record provider, endpoint family, source time, fetch time, cache state, freshness and terms-review date with normalized data.
3. Keep vendor payloads behind adapters and never make provider field names part of public domain schemas.
4. Cache aggressively within freshness requirements, respect `Retry-After`, and stop calling after a circuit opens.
5. Do not imply real-time data when it is delayed, cached, stale or unavailable.
6. A free price is not a license. External display/redistribution rights are an independent release gate.
7. Provider terms and official limits are rechecked at the start of the provider's implementation phase and before production deployment.

## 2. Source matrix

| Domain | Primary source | Authentication | Pilot use | Target cache | Attribution/freshness | Failure behavior | Status |
|---|---|---|---|---|---|---|---|
| SEC submissions and filing index | SEC EDGAR `data.sec.gov`/archives | Declared identifying User-Agent | 10-K, 10-Q, 8-K discovery and metadata | 2–6 h | SEC link, filing/acceptance/fetch time | Cached index; typed unavailable if absent | Approved |
| SEC filings | SEC EDGAR archives | Declared User-Agent | HTML/text evidence, compare and RAG | Permanent by SHA-256 | Accession, form, filing date, section, source URL | Preserve last parsed content; no invented section | Approved |
| Fundamentals | SEC XBRL Company Facts | Declared User-Agent | Statements and deterministic ratios | 12–24 h | Fact taxonomy/unit/period/form/source | Partial fields and lower confidence | Approved |
| Binance Spot | Official public market-data REST API | None for public market endpoints | Ticker, candles, book, trades, exchange info | 5 s–5 min by endpoint | Binance, event/source/fetch time, weight | Respect 429/418; stale/partial; disable by flag | Conditionally approved |
| Binance Futures | Official USDⓈ-M public market endpoints | None for selected public endpoints | Mark/index, funding, OI, public ratios/flow | 15 s–5 min | Binance, event/source/fetch time | Same, plus jurisdiction/reachability gate | Conditionally approved |
| General crypto | CoinGecko Demo or keyless public API | Demo key preferred; keyless fallback | Low-volume non-commercial educational pilot | 3–5 min and batching | Prominent “Data provided by CoinGecko”; ≥60 s freshness on Demo | Monthly budget, stale cache, partial fields | Pilot only |
| Stock quote/candles | No provider selected | TBD | Latest/delayed price and historical candles | 10–60 min | Must include provider and delay | Return unavailable; SEC research remains | Blocked on display rights |
| Company identity | SEC ticker/CIK file, then selected stock provider if licensed | User-Agent / TBD | Ticker/CIK/company/exchange mapping | Daily | SEC/provider | Cached mapping | Approved for SEC fields |
| Local embeddings | Selected open-source sentence-transformer | Local | Filing chunk vectors | Permanent per content+model hash | Model name/version/hash | BM25-only retrieval | Selection gate |
| Local LLM | Small quantized instruct model via Ollama | Local | Optional report/answer wording | Report cache 1–6 h | Model/prompt/schema version | Template/retrieval-only fallback | Benchmark gate |

“Conditionally approved” means the API is technically suitable but production use depends on current terms, region and endpoint reachability. It never authorizes trading.

## 3. SEC adapter rules

- Use an application/company name plus monitored contact email in `User-Agent`.
- Enforce a global rate below the SEC maximum of 10 requests/second; initial ceiling is 5 requests/second with concurrency 2.
- Cache ticker/CIK maps and submissions. Use conditional requests when supported.
- Store accession number, CIK, form, filing date, acceptance time, source URL and SHA-256 content hash.
- Allow only SEC hosts and expected paths; do not accept a user-supplied download URL.
- Parse defensively with size, MIME and decompression limits.
- SEC XBRL facts are normalized by concept, unit, period and form; duplicate/amended facts are resolved by deterministic policy and remain traceable.

Official references: [SEC access and fair-use guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data), [SEC data APIs](https://data.sec.gov/), and [SEC reuse FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions).

## 4. Binance adapter rules

- Spot public market calls prefer the documented market-data-only base endpoint where supported.
- Fetch `/exchangeInfo` and validate symbol/status/interval before market calls.
- Track endpoint weight and response usage headers, not only request count.
- On `429`, stop and obey `Retry-After`; repeated calls must not provoke a `418` IP ban.
- Set bounded depth/trade/candle limits so a user cannot amplify provider weight or response size.
- No routes, schemas, clients or credentials for orders, accounts, balances, positions, withdrawals or leverage changes.
- Futures data is feature-flagged independently from Spot and disabled where legal access or reachability is uncertain.

Official references: [Binance Spot REST API](https://developers.binance.com/en/docs/products/spot/rest-api) and [Binance USDⓈ-M Futures introduction](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/Introduction).

## 5. CoinGecko adapter and quota budget

The current Demo allowance is 10,000 calls/month and 100 calls/minute with data freshness from 60 seconds and required attribution. It has no production SLA or commercial license.

Initial budget:

| Workload | Calls/day target | Technique |
|---|---:|---|
| Global/trending snapshots | 48 | Batch and cache every 30 minutes |
| Popular market list | 96 | One batched call every 15 minutes during active periods |
| On-demand coin overview/history | 100 | Cache by coin/range; single-flight locks |
| Retries/headroom | 56 | Circuit breaker and bounded retry |
| Total target | ≤300/day | ≤9,000 in a 30-day month |

The provider manager hard-stops scheduled refreshes before the monthly cap and preserves quota for user requests. If the intended use becomes commercial or exceeds pilot terms, the module requires a suitable license or a replacement provider.

Official references: [CoinGecko API pricing and limits](https://www.coingecko.com/en/api/pricing) and [keyless public API intent](https://docs.coingecko.com/docs/keyless-public-api).

## 6. Stock-provider release gate

No reviewed free source currently satisfies both the expected request volume and clear multi-user external-display rights:

| Candidate | Free technical allowance | Rights/reliability finding | Decision |
|---|---|---|---|
| Twelve Data Basic | 8 credits/minute, 800/day | Basic is internal non-display; external display begins on a paid business tier | Do not use for multi-user display |
| Alpaca Basic | Free IEX data and historical allowance | Official support says Alpaca API data may not be redistributed | Do not use for multi-user display |
| Alpha Vantage free | Most endpoints, 25 requests/day | Too small for the target and no documented acceptance of this display model in reviewed material | Do not select |
| Massive/Polygon individual free | Free individual plan for selected data | Individual/business licensing must be resolved; free external-display right was not established | Do not select |
| Scraped Yahoo/Nasdaq/Stooq pages | Technically possible | Unofficial/undocumented access and display terms | Prohibited |

Phase 7 may implement the provider abstraction, symbols, SEC fundamentals, analytics over legally sourced data and labelled offline fixtures. It may not call a “live stock” feature production-ready until the owner records a provider/plan, terms URL, quota, delay and display permission.

Safe product behavior without a licensed feed:

- Stock pages still show SEC identity, statements, ratios, filings, comparisons and RAG.
- Price-dependent fields use `freshness: unavailable`, `partial: true` and a precise warning.
- Quick demos use static dated fixtures with an “offline demonstration data” badge; fixtures are never described as current.
- Risk renormalizes available components and lowers data confidence.

Official candidate references: [Twelve Data individual pricing](https://twelvedata.com/pricing), [Twelve Data usage rights](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage), [Twelve Data business pricing](https://twelvedata.com/pricing-business), [Alpaca redistribution statement](https://alpaca.markets/support/redistribute-alpaca-api), and [Alpha Vantage request limit](https://www.alphavantage.co/premium/).

## 7. Provider normalization contract

Every adapter returns an internal Pydantic model with:

- Canonical asset identity and provider identity.
- Decimal-safe values and normalized UTC timestamps.
- Source/fetch timestamps, delay class and a provider request ID where available.
- Missing fields as `null` plus structured warnings—not fabricated zeros.
- Raw payload hash and schema version for audit/debugging; raw payload persistence is opt-in and retention-limited.
- Terms-review version and attribution label when data is persisted or displayed.

## 8. Source verification in reports

Reports include a source manifest whose entries identify provider, title/type, source URL, source timestamp, fetch timestamp, cache/freshness, content hash and fields supported. LLM output can reference only manifest IDs supplied in structured context. Citation validation rejects unknown IDs and falls back to a deterministic template.

