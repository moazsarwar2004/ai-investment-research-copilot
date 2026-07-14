# Free Resource Verification

Checked against official documentation on 2026-07-13. Free plans and terms may change; recheck before the relevant implementation phase and production deployment.

## 1. Verification result

| Resource | Official allowance observed | Fit for pilot | Conditions and decision |
|---|---|---|---|
| Oracle Cloud Always Free A1 | 1,500 OCPU-hours and 9,000 GB-hours/month; for Always Free tenancy this is currently 2 OCPUs and 12 GB total | Conditional | Home-region capacity is not guaranteed; account/card may be required; keep Compose portable |
| OCI Object Storage | 20 GB combined after trial and 50,000 API requests/month | Yes, small backups | Client-side encrypt; enforce retention and size alarms; same-tenancy copy is not full provider disaster isolation |
| OCI Email Delivery | Free-tier page advertises 3,000 emails/month, while the current service-limits table shows an Always Free daily send limit of 0 | Not selected by default | Treat the official discrepancy as blocking; enable only after the account shows a usable no-cost quota, a controlled domain, SPF/DKIM and a smoke test |
| GitHub Actions | Public repos use standard runners free; GitHub Free private repos include 2,000 minutes/month and 500 MB artifact storage | Yes | Use Linux runners, concurrency/cancel controls and short artifact retention |
| GitHub Container Registry | Container image storage and bandwidth currently free; public images pull anonymously | Yes, policy-sensitive | GitHub promises notice before pricing change; use immutable tags and image cleanup |
| Grafana Cloud Free | Free forever; current docs advertise 10k metrics, 50 GB logs, 50 GB traces; pricing shows 14-day retention | Yes | Sampling/cardinality budgets required; avoid PII/secrets |
| Better Stack Free | Pricing lists 10 monitors/heartbeats headline, one status page, email/Slack alerts, plus free telemetry allowances | Yes, account check | Required 8 checks fit only after confirming the account UI interprets monitor/heartbeat quotas as expected |
| Cloudflare authoritative DNS | Free DNS available on all plans | DNS only | Requires a domain the owner controls; domain registration itself is not free |
| DuckDNS | Free dynamic DNS subdomains | Conditional | No SLA; acceptable pilot fallback, not a strong long-term production identity |
| Caddy | Open-source reverse proxy with automatic public HTTPS for qualifying DNS names | Yes | Needs DNS pointed at the VM, ports 80/443 and persistent writable certificate storage |
| SEC EDGAR | Public/free access and reuse; maximum 10 requests/second with declared User-Agent | Yes | Use lower self-imposed limit, caching and responsible identification |
| Binance public market API | Public market endpoints; weighted limits; 429 with `Retry-After`, repeated violation can cause 418 ban | Conditional | Region/terms/reachability and feature flags; no authenticated trading APIs |
| CoinGecko Demo | $0, 10,000 calls/month, 100/minute, freshness from 60 seconds, attribution required | Pilot only | Testing/exploration/non-commercial use, no SLA/commercial license; hard budget and cache |
| Free stock feeds reviewed | Technical free tiers exist | No clean selection | External display/redistribution rights not established at $0 for this multi-user app |

## 2. Official evidence

### Oracle Cloud

- [OCI Free Tier](https://docs.oracle.com/iaas/Content/FreeTier/freetier.htm) currently describes Always Free resources and the 2-OCPU/12-GB A1 total for Always Free tenancies.
- [Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) lists 1,500 A1 OCPU-hours, 9,000 GB-hours, 20 GB Object Storage, 50,000 object requests and the email allowance.
- The same Always Free page warns that instances meeting all low CPU/network/memory criteria over seven days may be reclaimed. Normal application load is not a reason to generate artificial utilization; monitoring and portable recovery are the mitigation.
- [OCI service limits](https://docs.oracle.com/en-us/iaas/Content/General/service-limits/default.htm) currently shows `max-emails-day` as 0 for Always Free, which conflicts with the Free Tier page's monthly email statement. Email therefore remains disabled until the actual tenancy proves a usable free allowance.

Conclusion: preferred first host, not an availability guarantee. Provisioning and a seven-day observation are deployment entry gates. OCI email is not an approved dependency at this baseline.

### GitHub

- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) documents free standard runners for public repos and 2,000 included monthly minutes/500 MB artifacts on GitHub Free private repos.
- [GitHub Packages billing](https://docs.github.com/en/billing/concepts/product-billing/github-packages) states that Container Registry image storage/bandwidth is currently free and that users will receive advance notice of a policy change.
- [Container Registry permissions](https://docs.github.com/en/packages/learn-github-packages/about-permissions-for-github-packages) documents anonymous pulls for public container images.

Conclusion: suitable for low-volume CI/CD. Private source with private images must stay within account quotas or use a self-hosted runner/registry path.

### Monitoring

- [Grafana Cloud documentation](https://grafana.com/docs/grafana/latest/introduction/grafana-cloud/) advertises free-forever 10k metrics, 50 GB logs and 50 GB traces.
- [Grafana pricing](https://grafana.com/pricing/?tab=free) shows a $0 always-free tier and 14-day telemetry retention.
- [Better Stack pricing](https://betterstack.com/pricing) lists the current personal-project free allowances, monitors/heartbeats, status page and alerts.

Conclusion: use Grafana for metrics/dashboards and Better Stack for external checks/heartbeats. Keep local structured logs as a short fallback and control telemetry volume.

### DNS and HTTPS

- [Cloudflare DNS FAQ](https://developers.cloudflare.com/dns/faq/) confirms free authoritative DNS on all plans, but the user must already control a domain.
- [DuckDNS FAQ](https://www.duckdns.org/faqs.jsp) describes its donation-supported free dynamic DNS service.
- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https) documents certificate provisioning, renewal and HTTP-to-HTTPS redirection for qualifying public DNS names.

Conclusion: a DuckDNS hostname can satisfy a zero-cost pilot, while an owned domain plus Cloudflare is the more stable production identity. A registered custom domain is an optional cost, not a hidden requirement for the application to run.

### Data providers

- [SEC access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) states a current maximum of 10 requests/second and requires a declared User-Agent.
- [SEC webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions) states that government-created and public EDGAR filing content is free to access and reuse.
- [Binance Spot API](https://developers.binance.com/en/docs/products/spot/rest-api) documents public market-data endpoints, weighted limits, `429`, `Retry-After` and `418` behavior.
- [CoinGecko pricing](https://www.coingecko.com/en/api/pricing) gives the current Demo quota/freshness/attribution and indicates no commercial license on Demo.
- [CoinGecko keyless API](https://docs.coingecko.com/docs/keyless-public-api) describes low-volume testing and non-commercial educational intent with dynamic IP limits.

Conclusion: SEC is the strongest free source. Binance and CoinGecko require quota/terms/reachability controls and are not SLA-backed.

### Stock data candidates

- [Twelve Data pricing](https://twelvedata.com/pricing) lists Basic at 8 credits/minute and 800/day, but labels it internal non-display.
- [Twelve Data usage rights](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage) says individual plans do not permit redistribution or commercial display to third parties.
- [Twelve Data business pricing](https://twelvedata.com/pricing-business) keeps Basic internal non-display and places external display on a paid tier.
- [Alpaca redistribution FAQ](https://alpaca.markets/support/redistribute-alpaca-api) says Alpaca API data cannot be redistributed.
- [Alpha Vantage premium page](https://www.alphavantage.co/premium/) identifies the standard free limit as 25 requests/day.

Conclusion: none is approved for this application's free multi-user stock display. Do not substitute an unofficial scraper.

## 3. Zero-cost operating budget

| Budget | Guardrail |
|---|---|
| Compute | Stay within the account's A1 Always Free shape; alert on sustained memory >80%, disk >75%, load and OOM events |
| Object storage | Alert at 12 GB and stop nonessential archives at 16 GB; never approach 20 GB without a restore/retention decision |
| CoinGecko | Target ≤9,000 of 10,000 monthly calls; stop scheduled refresh before exhausting reserve |
| GitHub Actions | Cancel superseded runs; Linux only; target <1,500 of 2,000 private-repo minutes |
| CI artifacts | Retain test artifacts 7 days or less; do not upload model weights as workflow artifacts |
| Telemetry | Low-cardinality metrics, trace sampling, redaction and daily ingestion dashboard |
| External monitors | Fit the eight required checks within the verified account quota; combine where responsible |
| Email | Disabled until domain/authentication/quota smoke test; daily app-level send cap |

## 4. Reverification checklist

Before Phase 20, record screenshots or exported account limits for OCI, GitHub, Grafana, Better Stack and the selected DNS/email provider. Re-open every official link above, update this date, and fail deployment if the configured service would incur an unapproved charge.
