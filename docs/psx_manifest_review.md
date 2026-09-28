# PSX fundamentals human-review package

Prepared: 2026-09-19. Human-approved: 2026-09-27 by **Moaz Sarwar**. The
approved artifact is `data/psx/psx_fundamentals.approved.json`.

The application checked schema, source host, page bounds, unit conversion,
duplicate periods, gross-profit arithmetic, and assets = liabilities + equity.
The named human reviewer subsequently compared the items below with the linked
reports and attested approval.

## AI technical re-verification - 2026-09-27

This is additional machine/AI verification, not human approval:

- The locally reviewed Systems PDF has 276 pages and SHA-256
  `408c201ad0421cebaad3e75b9486fcedd87252defc169b510e06e41c6339d60f`.
- The locally reviewed Meezan PDF has 413 pages and SHA-256
  `40a8984bb399a0a749db509f501237af1054a922d06544504df69bf875b4749b`.
- Systems PDF pages 198, 199, and 202 were visually rechecked for statement
  basis, FY2025/FY2024 columns, values, EPS labeling, and cash-flow totals.
- Meezan PDF pages 297, 298, and 301 were visually rechecked for consolidated
  basis, `Rupees in '000`, the EPS scale exception, values, and cash-flow
  context.
- Manifest schema, provenance, page, unit-conversion, duplicate-period, and
  accounting-consistency validation passed.
- At the time of this AI-only re-verification, the production gate correctly
  exited `2`; the later human approval is recorded separately below.

## Human approval - 2026-09-27

Moaz Sarwar attested personal review of company identity, PSX symbols,
consolidated statement basis, FY2024/FY2025 figures, units, EPS treatment,
source pages, and accounting checks for both companies. The approved manifest
records the reviewer and timezone-aware timestamp and passes the production
publication gate with both symbols published.

## Systems Limited (`PSX:SYS`)

- Official report: https://www.systemsltd.com/sites/default/files/2026-04/Systems%20Limited-Annual%20Report%202025.pdf
- Official listing/index: https://www.systemsltd.com/financial-reports
- Document SHA-256: `408c201ad0421cebaad3e75b9486fcedd87252defc169b510e06e41c6339d60f`
- PDF pages: 276
- Publication evidence: official index labels it “Annual report 2025” and
  “April, 2026”; no exact day was recorded.
- Selected statements: consolidated, PKR base units.

| Fact | Report page | FY2025 | FY2024 |
| --- | ---: | ---: | ---: |
| Revenue | 199 | 80,391,884,594 | 67,473,021,160 |
| Cost of revenue | 199 | 57,982,619,705 | 51,315,319,855 |
| Gross profit | 199 | 22,409,264,889 | 16,157,701,305 |
| Operating profit | 199 | 12,006,337,696 | 8,271,972,779 |
| Profit for the year | 199 | 11,040,583,934 | 7,460,012,773 |
| Basic EPS (PKR/share) | 199 | 7.52 | 5.11 (restated) |
| Total assets | 198 | 75,488,572,268 | 57,547,344,392 |
| Total liabilities (derived from stated current + non-current totals) | 198 | 26,909,749,751 | 18,816,678,736 |
| Total equity including NCI | 198 | 48,578,822,517 | 38,730,665,656 |
| Cash and bank balances | 198 | 13,504,721,300 | 7,820,717,667 |
| Operating cash flow | 202 | 10,877,008,675 | 4,117,414,601 |

Automated checks:

- FY2025 gross profit: `80,391,884,594 - 57,982,619,705 = 22,409,264,889`.
- FY2025 balance: `26,909,749,751 + 48,578,822,517 = 75,488,572,268`.
- FY2024 gross profit: `67,473,021,160 - 51,315,319,855 = 16,157,701,305`.
- FY2024 balance: `18,816,678,736 + 38,730,665,656 = 57,547,344,392`.

Human review:

- [x] Company identity, PSX symbol, and official domain checked.
- [x] PDF hash/page count checked against the file actually reviewed.
- [x] Consolidated (not unconsolidated) pages confirmed.
- [x] Every FY2025 and FY2024 value above checked visually.
- [x] Restated FY2024 EPS label retained.
- [x] Liability/equity derivations and accounting equations recalculated.
- [x] Source links open from the review network; production smoke validation remains a deployment check.

## Meezan Bank Limited (`PSX:MEBL`)

- Official report: https://www.meezanbank.com/wp-content/themes/mbl/downloads/annualreport2025.pdf
- Official report index: https://www.meezanbank.com/financial-information/
- Official identity: https://www.meezanbank.com/info-for-investors/
- Document SHA-256: `40a8984bb399a0a749db509f501237af1054a922d06544504df69bf875b4749b`
- PDF pages: 413
- Board approval stated in the report: 2026-02-09. Exact website posting date
  was not recorded, so the manifest does not invent one.
- Selected statements: consolidated bank statements, reported in PKR thousands;
  normalized manifest values multiply statement figures by 1,000. EPS remains
  PKR per share and is not multiplied.

| Fact | PDF page / printed page | FY2025 reported (`000`) | FY2024 reported (`000`) |
| --- | ---: | ---: | ---: |
| Total income | 298 / 296 | 290,647,948 | 318,891,381 |
| Total other expenses | 298 / 296 | 89,850,201 | 86,847,165 |
| Profit before taxation | 298 / 296 | 200,298,738 | 226,279,254 |
| Profit after taxation | 298 / 296 | 92,178,462 | 103,719,335 |
| Basic EPS (PKR/share, scale 1) | 298 / 296 | 50.47 | 57.28 |
| Total assets | 297 / 295 | 4,819,935,454 | 3,912,188,601 |
| Total liabilities | 297 / 295 | 4,531,737,389 | 3,658,558,381 |
| Net assets including NCI | 297 / 295 | 288,198,065 | 253,630,220 |
| Deposits and other accounts | 297 / 295 | 3,302,337,407 | 2,584,583,671 |
| Islamic financing and related assets | 297 / 295 | 1,640,934,798 | 1,514,755,936 |
| Investments | 297 / 295 | 2,608,334,204 | 1,878,852,841 |

Automated checks after ×1,000 normalization:

- FY2025 balance: `4,531,737,389 + 288,198,065 = 4,819,935,454` thousand.
- FY2024 balance: `3,658,558,381 + 253,630,220 = 3,912,188,601` thousand.
- Corporate current-ratio and debt-to-equity calculations are intentionally
  disabled. Bank ratios use total-income, deposit, financing, equity/assets,
  ROA, and ROE inputs where present.

Human review:

- [x] Company identity, `MEBL`, CUIN, and official domain checked.
- [x] PDF hash/page count checked against the file actually reviewed.
- [x] Consolidated pages 295–296 selected, not unconsolidated pages 190–191.
- [x] “Rupees in '000” unit and EPS exception checked visually.
- [x] Every FY2025 and FY2024 value above checked visually.
- [x] Bank-specific labels and calculations reviewed by someone familiar with
      bank financial statements.
- [x] Accounting equations and ×1,000 normalized values recalculated.
- [x] Source links open from the review network; production smoke validation remains a deployment check.

## Publication sign-off

Do not sign until all company checkboxes pass.

- Reviewer full name: Moaz Sarwar
- Review timestamp with timezone: 2026-09-27T10:13:41.5190978+05:00
- Notes/corrections: Reviewer attested verification of both companies; no corrections reported.

After sign-off, update only the reviewed company entry:

1. Set every reviewed fact's `review_status` to `human_verified`.
2. Set the five `review` check fields to `true`.
3. Record the real `human_reviewer` and timezone-aware `reviewed_at`.
4. Set `status` to `approved` last.
5. Run `python scripts/validate_psx_manifest.py <file> --require-all-approved`.
6. Have a second person review the Git diff before deployment when practical.
