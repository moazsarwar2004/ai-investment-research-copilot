# Phase 0 — Production Planning Baseline

Status: complete and ready for review  
Baseline date: 2026-07-13  
Target: a non-commercial, research-only pilot for 5–15 users and fewer than 10 concurrent users

## 1. Objective

Freeze a buildable and testable product boundary before application code is created. This phase validates the architecture, names the external constraints, defines the database and API contracts, and turns the 21 requested phases into measurable release gates.

## 2. Why this phase is required

Market-data licenses and free cloud allowances are part of the system design, not procurement details. A technically working application can still be unsafe or non-deployable if it redistributes data without permission, exceeds a provider quota, exposes internal services, or assumes cloud capacity that is not available. The documents below make those constraints explicit before they become code.

## 3. Phase 0 deliverables

| Deliverable | File | Purpose |
|---|---|---|
| Final requirements | [requirements.md](requirements.md) | Scope, roles, functional requirements, SLOs, security and acceptance gates |
| Architecture | [architecture.md](architecture.md) | Runtime, request flow, deployment topology, trust boundaries and sizing |
| Database ERD | [database_design.md](database_design.md) | Tables, relationships, constraints, indexes and retention |
| API route list | [api_docs.md](api_docs.md) | Versioned endpoints, authorization and response conventions |
| Data-source matrix | [data_sources.md](data_sources.md) | Provider purpose, caching, attribution, failures and licensing gates |
| Free-resource verification | [free_resource_verification.md](free_resource_verification.md) | Official-source check dated 2026-07-13 |
| Risk register | [risk_register.md](risk_register.md) | Ranked technical, security, legal and operational risks |
| Milestone plan | [milestones.md](milestones.md) | Phase order, entry/exit gates and evidence required |
| Validation record | [phase_0_validation.md](phase_0_validation.md) | Commands, expected output, common errors and completion checklist |

## 4. Decisions made

1. Use a modular monolith. The FastAPI API, Celery worker and Celery Beat scheduler share one Python codebase and image, but run as separate processes/containers.
2. Keep Streamlit as a replaceable client. It calls versioned backend APIs and contains no pricing, risk, provider, authorization or persistence logic.
3. PostgreSQL is the system of record; Redis is disposable acceleration and queue infrastructure. Losing Redis must not lose user-owned records.
4. Use deterministic analytics first. An unavailable model, embedding service or Ollama instance degrades trend/RAG/report features to documented fallbacks without breaking core research.
5. Treat every provider response and filing chunk as untrusted input. Normalize it before storage or use, and never execute document instructions.
6. Host the first pilot on a single portable Linux VM only after an account-level capacity check. Oracle Cloud Always Free is preferred but not guaranteed.
7. Do not expose PostgreSQL, Redis, Ollama, MLflow, OpenTelemetry, worker, scheduler or `/metrics` through the public reverse proxy.
8. Do not select a free stock quote feed until external-display rights are documented. The stock module can ship SEC fundamentals/filings and a clearly labelled offline demo snapshot, but a live multi-user price display is a release gate.

## 5. Explicit non-goals for version 1

- Real-money orders, exchange-secret storage, withdrawals, leverage changes or automated trading.
- Personalized advice, portfolio optimization, guaranteed signals or return claims.
- Kubernetes, Kafka, service mesh, multi-region failover or independently deployed microservices.
- Paid LLM APIs or a dependency on Ollama for correctness.
- A commercial availability SLA.
- Silent use of scraped or unofficial finance endpoints.

## 6. Phase 0 decision gates

The following items require owner confirmation or an account test before their implementation phase begins:

| Gate | Required before | Pass condition | Safe fallback |
|---|---|---|---|
| Stock display license | Phase 7 | Written provider terms permit the intended 5–15-user display | SEC-only stock research plus labelled offline demo data; live quote fields return `unavailable` |
| OCI A1 capacity | Phase 20 | An eligible 2-OCPU/12-GB A1 VM can be provisioned in the home region | Any Ubuntu ARM64/AMD64 VPS or self-hosted Linux host using the same Compose files |
| ARM64 ML dependencies | Phase 11 | Locked Python packages and model runtime pass an ARM64 image build/smoke test | Build AMD64 for another host or use deterministic trend rules |
| Local LLM performance | Phase 14 | Selected quantized instruct model meets schema validity and latency budget on the target VM | Template report and retrieval-only RAG answer |
| Crypto pilot terms | Phase 6 | CoinGecko account/terms still permit this non-commercial educational pilot | Cached snapshots and Binance spot/global comparison where allowed |
| Binance jurisdiction/reachability | Phases 5 and 9 | Production VM can reach the required public endpoints and use is permitted | Feature flag disables the affected Binance module |
| Transactional email | Phase 16 | Sender domain, SPF/DKIM and a successful quota smoke test are available | In-app notifications only |

No Phase 1 source scaffolding is included in this baseline. That preserves the requested phase gate.

## 7. Recommended Git commit

```text
docs: establish phase 0 production planning baseline
```

