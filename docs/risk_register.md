# Risk Register

Scoring: likelihood and impact are 1 (low) to 5 (very high). Exposure is likelihood × impact. Owners are roles until named people are assigned.

| ID | Risk | L | I | Exposure | Prevent/detect | Contingency / release gate | Owner |
|---|---|---:|---:|---:|---|---|---|
| R-01 | No zero-cost stock provider grants suitable multi-user display rights | 5 | 5 | 25 | Terms review with official URLs; prohibit scrapers; provider contract includes license metadata | Phase 7 cannot be production-complete; ship SEC-only research and unavailable quote fields until rights are documented | Product owner + Security |
| R-02 | OCI A1 capacity is unavailable or allowance changes | 4 | 5 | 20 | Provision before production work; track official limits; portable Compose; ARM64/AMD64 builds | Move to any user-authorized Ubuntu host; no provider-specific app dependency | DevOps |
| R-03 | Idle Always Free VM is reclaimed | 3 | 5 | 15 | External uptime, backup and host-state alerts; daily remote encrypted backup; infrastructure runbook | Recreate host from Compose and restore within 4-hour RTO; never create fake workload solely to avoid reclamation | DevOps |
| R-04 | 2 OCPUs/12 GB cannot support Postgres, embeddings and Ollama concurrently | 4 | 4 | 16 | Memory/CPU budgets; worker concurrency 1; one small quantized model; load and soak tests | Disable/unload Ollama, use template fallback; move LLM to separate user-owned host | AI/DevOps |
| R-05 | ARM64 Python/ML dependency or image is unavailable | 3 | 4 | 12 | Multi-arch CI smoke build early; lock hashes; test wheels/model runtime | Use deterministic rules, an AMD64 host, or build a reviewed wheel in CI | ML/DevOps |
| R-06 | CoinGecko quota or pilot terms are exceeded | 3 | 4 | 12 | Monthly hard budget, batching, TTLs, usage dashboard and terms review | Stop scheduled refresh; serve labelled cached data; disable provider or obtain approved plan | Backend/Product |
| R-07 | Binance blocks the VM/region or changes endpoint limits | 3 | 4 | 12 | Startup reachability check, exchange info cache, weight/429 monitoring, independent feature flags | Disable Spot/Futures separately and show provider unavailable; no alternate unofficial endpoint | Backend/Ops |
| R-08 | SEC throttles or blocks undeclared automation | 2 | 4 | 8 | Identifying User-Agent, 5 req/s ceiling, caching, conditional requests, backoff | Pause ingestion and serve previously parsed filings with freshness warning | Data engineering |
| R-09 | Provider data is wrong, delayed, ambiguous or schema-changed | 4 | 4 | 16 | Strict adapters, schema fixtures, invariants, cross-source comparison where legal, timestamp validation | Reject invalid fields; partial response; quarantine schema and alert provider status | Backend/Data |
| R-10 | Symbol collision returns the wrong crypto/stock | 3 | 4 | 12 | Canonical provider IDs, exchange/asset type in keys, explicit search disambiguation | Refuse ambiguous request and require selected canonical ID | Backend |
| R-11 | Prompt injection in SEC filing influences the LLM | 3 | 5 | 15 | Retrieved content marked untrusted; structured context; no tools; system rule; injection tests; citation allowlist | Retrieval-only answer/template; quarantine failed output | AI Security |
| R-12 | LLM hallucinates a fact or citation | 4 | 5 | 20 | Verified structured input, JSON schema, source manifest, sentence/citation validation, evaluation dataset | Reject generation and return deterministic template/evidence | AI/LLMOps |
| R-13 | Vector retrieval misses material evidence | 3 | 4 | 12 | Hybrid BM25+dense, metadata filters, reranking, labeled evaluation set, no-result/citation metrics | State insufficient evidence; expose evidence; improve corpus/evaluation before threshold change | RAG/ML |
| R-14 | Time-series leakage inflates model metrics | 3 | 4 | 12 | Time-based split, fit transforms only on train, leakage tests and code review | Reject artifact activation and use rule fallback | ML |
| R-15 | Model drift degrades trend classification | 3 | 3 | 9 | Feature-distribution monitoring, rolling evaluation, confidence threshold and active version registry | Mark degraded; deactivate model; use rule fallback; retrain through approved job | MLOps |
| R-16 | Refresh-token theft/replay compromises an account | 3 | 5 | 15 | Short access lifetime, hashed rotating refresh tokens, reuse-family revocation, TLS, secure handling and audit | Revoke all sessions, reset password, incident review and user notification process | Security |
| R-17 | Streamlit session/token handling leaks credentials | 3 | 5 | 15 | Server-memory only; no browser localStorage; redaction tests; no token serialization/caching; TLS | Force re-login on reconnect; revoke family; consider React/BFF migration if controls fail review | Frontend/Security |
| R-18 | Authorization bug exposes another user's reports/watchlists/alerts | 3 | 5 | 15 | Owner-scoped repository predicates, backend RBAC, object-level API tests, admin path separation | Disable affected route, audit access and execute incident process | Backend/Security |
| R-19 | Secrets or private content enter logs/traces | 3 | 5 | 15 | Central redaction, structured allowlist fields, test canaries, low-data telemetry | Rotate secret, purge where possible, notify and perform incident review | Security/Ops |
| R-20 | Redis loss drops jobs or corrupts cache behavior | 3 | 4 | 12 | Durable job row before enqueue, idempotent tasks, Redis persistence policy, cache/source separation | Requeue pending DB jobs after Redis recovery; core records remain in Postgres | Backend/Ops |
| R-21 | Duplicate workers send repeated alerts/reports | 3 | 3 | 9 | DB unique fingerprints/idempotency keys, row locks and cooldown transaction | Reconcile duplicates, suppress delivery and repair job state | Backend |
| R-22 | Migration makes rollback unsafe | 2 | 5 | 10 | Expand/migrate/contract, previous-version compatibility tests, backup before contract | Roll application back; restore DB only through runbook if migration is destructive | Database/DevOps |
| R-23 | Backup exists but cannot be restored | 3 | 5 | 15 | Checksums, client-side encryption key custody, daily heartbeat, monthly automated restore test | Incident escalation; recover latest verified generation; document actual RPO | Database/Ops |
| R-24 | Same-cloud backup is lost with the OCI tenancy | 2 | 5 | 10 | Export backup index/checksums and support a second user-controlled destination | Add cross-provider/user-owned encrypted copy before data importance exceeds risk appetite | Product/Ops |
| R-25 | Free monitoring/CI/container policies change and cause cost or outage | 3 | 3 | 9 | Monthly allowance dashboard, zero spend budgets, deployment recheck and portable configs | Disable nonessential export, use local tools/self-hosted runner, change provider | DevOps |
| R-26 | Telemetry cardinality exceeds a free allowance | 3 | 3 | 9 | Label allowlist; prohibit user/asset/request IDs as labels; sampling and ingestion alerts | Drop/summarize high-cardinality signal and keep short local logs | Observability |
| R-27 | Single VM/disk failure causes full outage | 3 | 5 | 15 | Persistent volumes, health checks, restart policies, remote backups and reproducible host bootstrap | Rebuild/restore; accept no HA under the free-first constraint | DevOps/Product |
| R-28 | Email deliverability/quota blocks alerts or password flows | 3 | 3 | 9 | SPF/DKIM, sender/domain checks, bounded retries and quota smoke test | In-app notifications; admin-assisted recovery until verified email is configured | Ops/Security |
| R-29 | Financial wording is interpreted as personalized advice | 3 | 5 | 15 | Fixed disclaimer, neutral research language, no portfolio/user-finance inputs, output tests | Disable generation template/version and review content policy | Product/Legal |
| R-30 | Data retention conflicts with privacy/account deletion | 2 | 4 | 8 | Retention map, minimization, deletion/anonymization jobs and audit tombstones | Suspend deletion automation, perform reviewed manual process and fix policy/code | Security/Database |

## 1. Highest-priority gates

The project does not pass production acceptance while any of these remain unresolved:

- R-01: stock quote display rights.
- R-02/R-03: target host provisioned, observed and recoverable.
- R-11/R-12/R-13: RAG/LLM evaluation thresholds and fallbacks demonstrated.
- R-16/R-18/R-19: authentication, ownership and redaction security tests passing.
- R-22/R-23: rollback-compatible migration and verified restore.

## 2. Review cadence

- Review at the start and exit of every phase.
- Re-score after provider terms, architecture, model or deployment changes.
- Any exposure ≥15 requires an explicit owner and testable mitigation before the dependent phase exits.
- Closed risks remain in history with closure evidence; they are not deleted.

