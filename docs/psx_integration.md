# PSX price licensing and fundamentals operations

Review date: 2026-09-26.

This document separates implemented controls, verified source facts, and work
that still needs external market-data authorization. New or changed financial
reports continue to require human review. Public accessibility, a delayed
quote, or a free endpoint is not treated as permission to display or
redistribute PSX data.

External-action status:

- On 2026-09-27, the project owner sent the licensing request in section 3 to
  `marketdatarequest@psx.com.pk` from the connected owner email account. Gmail
  confirmed the message in Sent. A response or quotation is still pending.
- Sending the request does not grant any data rights. The market-price adapter
  must remain disabled until PSX or an authorized supplier provides written
  authorization covering this application's exact use.

## 1. Selected approach

### Prices

No external PSX price adapter is active. The application keeps its existing
owner-private CSV workflow as the usable fallback and now requires a future
provider record to state:

- real-time, delayed, end-of-day, or historical data class;
- written authorization reference and scope;
- public-display, derived-analytics, caching, retention, and attribution terms;
- review date, expiry date where applicable, plan, and quote delay.

The preferred licensed pilot is end-of-day plus historical OHLCV. It supports
the product's research purpose and all existing technical calculations without
paying for execution-grade depth. Delayed quotes can be added only if the quote
and public-display terms are acceptable. This is a product preference, not a
claim that PSX has authorized it.

PSX's current notice says live or delayed prices, volumes, indices, PUCARS data,
website data, commercial use, and derived use require the applicable PSX rights
or prior approval. PSX also states that third parties using data from an
authorized redistributor still need PSX approval/license.

Official references:

- https://www.psx.com.pk/psx/product-and-services/data-services-vending
- https://www.psx.com.pk/psx/themes/psx/uploads/PSX_Data_Legal_Notice.pdf
- https://www.psx.com.pk/psx/themes/psx/uploads/Notice-Revised-Schedule-of-PSX-Service-Charges-w.e_.f-1st-July-2026_.pdf

### Fundamentals

The version-2 manifest stores official company-report facts with field-level
page, label, reported value, scale, statement basis, extraction method, source
document hash, and review status. Automated validation checks source hosts,
identity, duplicates, dates, page bounds, unit conversions, gross-profit
arithmetic, and the accounting equation.

SYS and MEBL were approved by Moaz Sarwar on 2026-09-27 after review of the
official reports. Their separate approved manifest passes the production gate.
The original candidate remains preserved. Candidate data still cannot
self-promote: the provider publishes only `approved` entries, and approval
requires a named reviewer, aware timestamp, five completed checks, and
`human_verified` evidence on every displayed fact.

## 2. Price-source comparison

| Option | Coverage/freshness | Display permission | Cost | Reliability | Decision |
| --- | --- | --- | --- | --- | --- |
| PSX direct | Real-time L1/L1+/L2, EOD, historical, PUCARS | Contract/approval required; no permission is currently held | Market-data quote required. Published technical-service charges are not themselves redistribution rights | Exchange source; commercial terms and delivery SLA must be contracted | Request EOD + historical public-display and derived-data terms first |
| Capital Stake, Mettis Global, or Sarmaaya | PSX lists these local clients as redistributors | PSX says third-party/subclient approval and license still apply | Quote required | Potentially simpler integration; SLA/API terms unverified | Ask for a joint quote only with written PSX approval for this app |
| Public PSX/Data Portal pages | Publicly viewable market and historical pages | Public access is not display/redistribution permission | No access fee visible | Not an application contract or stable API | Do not scrape or display |
| User-supplied CSV | Whatever legal history the user provides | Owner supplies it for private analysis; application does not redistribute it | No recurring app data fee | Quality and freshness depend on the user's source | Implemented fallback with source label/date and owner isolation |

The 2026 PSX technical-service schedule lists a Ticker API service charge, but
that fee must not be interpreted as public redistribution or derived-data
permission. A written scope is still required.

## 3. Exact external action for prices

Send the following request to `marketdatarequest@psx.com.pk`. Do not activate an
adapter until the response or contract answers every item.

```text
Subject: Public web-app license request — PSX EOD/historical data and derived analytics

We operate a small public investment-research and education web application.
It does not execute trades or provide personalized financial advice.

Please quote and confirm written permission for:
1. PSX end-of-day and historical daily OHLCV for listed equities;
2. display to unauthenticated and authenticated web users;
3. calculation and display of derived indicators and risk metrics;
4. server-side caching, database retention, backups, and disaster recovery;
5. development, staging, recruiter demonstrations, and production;
6. expected small initial user/request volume and the applicable scaling tiers;
7. required attribution, latency labels, audit/reporting, and geographic limits;
8. whether a named redistributor may supply the feed and what PSX sub-license
   or approval is still required;
9. fees, taxes, setup costs, API/feed specification, SLA, quota, and termination
   or data-deletion obligations.

Please state separately whether delayed quotes are available under the same
rights and price.
```

Record the executed authorization in `StockProviderLicense`; a price adapter
with `display_authorized=false`, missing scope/reference, or an inconsistent
latency label is rejected at startup.

## 4. Approved pilot and preserved candidate

The approved runtime manifest is
`data/psx/psx_fundamentals.approved.json`. The original extraction remains at
`data/psx/psx_fundamentals.candidate.json` for audit comparison. They contain:

| Company | Identity | Basis | Periods | Main facts | Publication state |
| --- | --- | --- | --- | --- | --- |
| Systems Limited | `PSX:SYS` | Consolidated | FY2024, FY2025 | Revenue, cost, gross/operating/net profit, EPS, assets, liabilities, equity, cash, operating cash flow | Human-approved; publishable |
| Meezan Bank Limited | `PSX:MEBL` | Consolidated bank model | FY2024, FY2025 | Total income, expenses, PBT, net income, EPS, assets, liabilities, equity, deposits, financing, investments | Human-approved; publishable |

Source pages and review checkpoints are in
[`psx_manifest_review.md`](psx_manifest_review.md).

## 5. Validate, approve, and run

Candidate validation remains available for audit comparison:

```powershell
python scripts/validate_psx_manifest.py
```

Production gate for the approved artifact (expected to exit `0`):

```powershell
python scripts/validate_psx_manifest.py data/psx/psx_fundamentals.approved.json --require-all-approved
```

That review procedure has been completed for this pilot. For future reports, a
human reviewer must repeat every checkbox independently; previous approval must
never be inherited by a new reporting period.

Configure and restart the API:

```powershell
$env:STOCK_FUNDAMENTALS_MANIFEST_PATH = "data/psx/psx_fundamentals.approved.json"
python -m uvicorn backend.app.main:app --reload
```

Smoke-check both companies:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/stocks/SYS/research?exchange=PSX&interval=1d&days=365"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/stocks/MEBL/research?exchange=PSX&interval=1d&days=365"
```

With the approved manifest configured, both calls return official-report
fundamentals while market-price fields remain honestly unavailable.

## 6. Refresh procedure

For every new annual or interim report:

1. Download from the company's official investor-relations page over HTTPS.
2. Record the exact URL, SHA-256, page count, publication evidence, period,
   currency, source unit, and consolidated/standalone basis.
3. Add facts as a new candidate period. Preserve missing fields as `null`.
4. Add evidence for each non-null fact, including PDF page and printed page.
5. Run automated validation and sector-aware calculation tests.
6. Complete a new independent human review; never inherit a previous approval.
7. Commit the new approved manifest, deploy/restart, and smoke-check its API and
   UI source links.

The manifest is loaded once at process startup and kept in memory. It does not
need Redis caching. Refresh is an explicit reviewed artifact deployment, which
also provides rollback through version control and the prior container image.

## 7. Failure behavior

- Invalid JSON, unknown fields, disallowed hosts, bad units, duplicate periods,
  or broken accounting identities fail application startup.
- Candidate/rejected companies validate but remain invisible to public APIs.
- Missing reports or price rights produce typed unavailable/partial responses;
  no substitute exchange, invented values, or stale-as-live labels are used.
- AI/deterministic briefs can use only fundamentals already present in the
  structured API response; missing evidence remains unavailable.
