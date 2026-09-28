"""Official SEC submissions and XBRL Company Facts fundamentals provider."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from itertools import zip_longest
from typing import ClassVar

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from backend.app.cache import CacheStatus
from backend.app.core.exceptions import ResourceNotFoundError
from backend.app.providers.adapters import ProviderAdapter
from backend.app.providers.manager import ProviderManager
from backend.app.providers.models import (
    AssetType,
    CanonicalAsset,
    DelayClass,
    Freshness,
    NormalizedPayload,
    OutboundRequest,
    ProviderHttpResponse,
    ProviderMeta,
    ProviderProvenance,
    ProviderRequest,
    ProviderResponse,
    ProviderWarning,
)
from backend.app.providers.stock_fundamentals import (
    CompanyReport,
    FinancialFactProvenance,
    FinancialPeriod,
    StockFundamentalsProvider,
    StockFundamentalsSnapshot,
)
from backend.app.providers.stocks import StockExchange, StockProfile

SEC_PROVIDER = "sec_edgar"
SEC_DATA_HOST = "data.sec.gov"
SEC_WWW_HOST = "www.sec.gov"
SEC_TERMS_REVIEW = "sec-public-data-reviewed-2026-08-06"
SEC_ATTRIBUTION = "U.S. Securities and Exchange Commission EDGAR"


class _SecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SecTickerCompany(_SecModel):
    cik: int = Field(ge=1)
    ticker: str
    title: str


class SecTickerMap(_SecModel):
    companies: list[SecTickerCompany] = Field(max_length=20_000)


class SecSubmissions(_SecModel):
    cik: str
    name: str
    sic_description: str | None = None
    fiscal_year_end: str | None = None
    website: AnyHttpUrl | None = None
    reports: list[CompanyReport] = Field(max_length=100)


class SecFact(_SecModel):
    canonical_name: str
    concept: str
    concept_priority: int = Field(ge=0)
    value: Decimal
    unit: str
    start: date | None = None
    end: date
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str
    filed: date
    accession_number: str
    frame: str | None = None


class SecFacts(_SecModel):
    cik: str
    entity_name: str
    facts: list[SecFact] = Field(max_length=20_000)


class _SecAdapter[DataT: BaseModel](ProviderAdapter[DataT]):
    provider: ClassVar[str] = SEC_PROVIDER
    terms_review_version: ClassVar[str] = SEC_TERMS_REVIEW
    attribution: ClassVar[str] = SEC_ATTRIBUTION
    allowed_hosts: ClassVar[frozenset[str]] = frozenset({SEC_DATA_HOST, SEC_WWW_HOST})

    def __init__(self, *, user_agent: str) -> None:
        self._headers = {
            "accept": "application/json",
            "user-agent": user_agent,
            "accept-encoding": "gzip, deflate",
        }


class SecTickerMapAdapter(_SecAdapter[SecTickerMap]):
    schema_version: ClassVar[str] = "sec-ticker-map-v1"
    data_model: ClassVar[type[BaseModel]] = SecTickerMap

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "sec.tickers":
            raise ValueError("ticker adapter received an unsupported operation")
        return OutboundRequest(
            url=AnyHttpUrl("https://www.sec.gov/files/company_tickers.json"),
            headers=self._headers,
        )

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[SecTickerMap]:
        del request
        if not isinstance(response.payload, dict):
            raise ValueError("SEC ticker response must be an object")
        companies: list[SecTickerCompany] = []
        for raw in response.payload.values():
            if not isinstance(raw, dict):
                continue
            cik = raw.get("cik_str")
            ticker = raw.get("ticker")
            title = raw.get("title")
            if (
                isinstance(cik, int)
                and isinstance(ticker, str)
                and isinstance(title, str)
            ):
                companies.append(
                    SecTickerCompany(cik=cik, ticker=ticker.upper(), title=title)
                )
        if not companies:
            raise ValueError("SEC ticker response contained no companies")
        return NormalizedPayload(
            data=SecTickerMap(companies=companies),
            delay_class=DelayClass.FILING,
        )


class SecSubmissionsAdapter(_SecAdapter[SecSubmissions]):
    schema_version: ClassVar[str] = "sec-submissions-v1"
    data_model: ClassVar[type[BaseModel]] = SecSubmissions

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "sec.submissions":
            raise ValueError("submissions adapter received an unsupported operation")
        cik = request.asset.provider_id
        if cik is None or len(cik) != 10 or not cik.isdigit():
            raise ValueError("SEC CIK must contain ten digits")
        return OutboundRequest(
            url=AnyHttpUrl(f"https://data.sec.gov/submissions/CIK{cik}.json"),
            headers=self._headers,
        )

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[SecSubmissions]:
        if not isinstance(response.payload, dict):
            raise ValueError("SEC submissions response must be an object")
        payload = response.payload
        cik_value = str(payload.get("cik", "")).zfill(10)
        name = payload.get("name")
        if not cik_value.isdigit() or not isinstance(name, str) or not name.strip():
            raise ValueError("SEC submissions identity is invalid")
        filings = payload.get("filings")
        recent = filings.get("recent") if isinstance(filings, dict) else None
        reports: list[CompanyReport] = []
        if isinstance(recent, dict):
            columns = [
                recent.get("accessionNumber", []),
                recent.get("form", []),
                recent.get("filingDate", []),
                recent.get("reportDate", []),
                recent.get("primaryDocument", []),
            ]
            if all(isinstance(column, list) for column in columns):
                cik_int = str(int(cik_value))
                for accession, form, filed, period_end, document in zip_longest(
                    *columns, fillvalue=None
                ):
                    if not all(
                        isinstance(value, str)
                        for value in (accession, form, filed, document)
                    ):
                        continue
                    base_form = form.removesuffix("/A")
                    if base_form not in {"10-K", "10-Q", "8-K"}:
                        continue
                    accession_path = accession.replace("-", "")
                    url = (
                        "https://www.sec.gov/Archives/edgar/data/"
                        f"{cik_int}/{accession_path}/{document}"
                    )
                    reports.append(
                        CompanyReport(
                            report_id=accession,
                            report_type=base_form,
                            title=f"{form} filed {filed}",
                            published_at=date.fromisoformat(filed),
                            period_end=(
                                date.fromisoformat(period_end)
                                if isinstance(period_end, str) and period_end
                                else None
                            ),
                            source_url=AnyHttpUrl(url),
                            source_name=SEC_ATTRIBUTION,
                            accession_number=accession,
                            amended=form.endswith("/A"),
                        )
                    )
                    if len(reports) >= 100:
                        break
        website_value = payload.get("website")
        website: AnyHttpUrl | None = None
        if isinstance(website_value, str) and website_value.startswith("https://"):
            website = AnyHttpUrl(website_value)
        latest = max(
            (item.published_at for item in reports if item.published_at is not None),
            default=None,
        )
        return NormalizedPayload(
            data=SecSubmissions(
                cik=cik_value,
                name=name.strip(),
                sic_description=(
                    str(payload["sicDescription"]).strip()
                    if payload.get("sicDescription")
                    else None
                ),
                fiscal_year_end=(
                    str(payload["fiscalYearEnd"])
                    if payload.get("fiscalYearEnd")
                    else None
                ),
                website=website,
                reports=reports,
            ),
            source_timestamp=(
                datetime.combine(latest, datetime.min.time(), tzinfo=UTC)
                if latest
                else None
            ),
            delay_class=DelayClass.FILING,
            partial=not reports,
            warnings=(
                []
                if reports
                else [
                    ProviderWarning(
                        code="sec_recent_filings_missing",
                        message=(
                            "SEC submissions contained no supported recent filings."
                        ),
                    )
                ]
            ),
        )


_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "cost_of_revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold"),
    "gross_profit": ("GrossProfit",),
    "operating_profit": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "eps": ("EarningsPerShareDiluted", "EarningsPerShareBasic"),
    "assets": ("Assets",),
    "current_assets": ("AssetsCurrent",),
    "liabilities": ("Liabilities",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "debt": (
        "LongTermDebtAndFinanceLeaseObligations",
        "LongTermDebt",
        "LongTermDebtNoncurrent",
    ),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "investing_cash_flow": ("NetCashProvidedByUsedInInvestingActivities",),
    "financing_cash_flow": ("NetCashProvidedByUsedInFinancingActivities",),
}


class SecCompanyFactsAdapter(_SecAdapter[SecFacts]):
    schema_version: ClassVar[str] = "sec-company-facts-v1"
    data_model: ClassVar[type[BaseModel]] = SecFacts

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "sec.company_facts":
            raise ValueError("company-facts adapter received an unsupported operation")
        cik = request.asset.provider_id
        if cik is None or len(cik) != 10 or not cik.isdigit():
            raise ValueError("SEC CIK must contain ten digits")
        return OutboundRequest(
            url=AnyHttpUrl(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"),
            headers=self._headers,
        )

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[SecFacts]:
        if not isinstance(response.payload, dict):
            raise ValueError("SEC Company Facts response must be an object")
        cik = str(response.payload.get("cik", "")).zfill(10)
        entity_name = response.payload.get("entityName")
        facts_root = response.payload.get("facts")
        us_gaap = facts_root.get("us-gaap") if isinstance(facts_root, dict) else None
        if (
            not cik.isdigit()
            or not isinstance(entity_name, str)
            or not isinstance(us_gaap, dict)
        ):
            raise ValueError("SEC Company Facts identity or taxonomy is invalid")
        facts: list[SecFact] = []
        for canonical_name, concepts in _CONCEPTS.items():
            for concept_priority, concept in enumerate(concepts):
                concept_payload = us_gaap.get(concept)
                if not isinstance(concept_payload, dict):
                    continue
                units = concept_payload.get("units")
                if not isinstance(units, dict):
                    continue
                preferred_units = (
                    ("USD/shares", "USD") if canonical_name == "eps" else ("USD",)
                )
                values: list[object] | None = None
                selected_unit = ""
                for unit in preferred_units:
                    candidate = units.get(unit)
                    if isinstance(candidate, list):
                        values = candidate
                        selected_unit = unit
                        break
                if values is None:
                    continue
                for raw in values:
                    if not isinstance(raw, dict):
                        continue
                    form = raw.get("form")
                    if not isinstance(form, str) or form.removesuffix("/A") not in {
                        "10-K",
                        "10-Q",
                    }:
                        continue
                    try:
                        value = Decimal(str(raw["val"]))
                        end = date.fromisoformat(str(raw["end"]))
                        filed = date.fromisoformat(str(raw["filed"]))
                        accession = str(raw["accn"])
                    except (KeyError, ValueError, InvalidOperation):
                        continue
                    if not value.is_finite():
                        continue
                    start_value = raw.get("start")
                    fiscal_year = raw.get("fy")
                    fiscal_period = raw.get("fp")
                    frame = raw.get("frame")
                    if isinstance(fiscal_year, int) and abs(end.year - fiscal_year) > 1:
                        continue
                    facts.append(
                        SecFact(
                            canonical_name=canonical_name,
                            concept=concept,
                            concept_priority=concept_priority,
                            value=value,
                            unit=selected_unit,
                            start=(
                                date.fromisoformat(start_value)
                                if isinstance(start_value, str)
                                else None
                            ),
                            end=end,
                            fiscal_year=(
                                fiscal_year if isinstance(fiscal_year, int) else None
                            ),
                            fiscal_period=(
                                fiscal_period
                                if isinstance(fiscal_period, str)
                                else None
                            ),
                            form=form,
                            filed=filed,
                            accession_number=accession,
                            frame=frame if isinstance(frame, str) else None,
                        )
                    )
        if not facts:
            raise ValueError("SEC Company Facts contained no supported financial facts")
        latest = max(item.filed for item in facts)
        return NormalizedPayload(
            data=SecFacts(cik=cik, entity_name=entity_name, facts=facts),
            source_timestamp=datetime.combine(latest, datetime.min.time(), tzinfo=UTC),
            delay_class=DelayClass.FILING,
        )


_INSTANT_CONCEPTS = {
    "assets",
    "current_assets",
    "liabilities",
    "current_liabilities",
    "equity",
    "debt",
    "cash",
}
_ANCHOR_CONCEPTS = {"revenue", "operating_profit", "net_income"}


def _best_fact(candidates: list[SecFact]) -> SecFact:
    return max(
        candidates,
        key=lambda item: (
            item.filed,
            item.form.endswith("/A"),
            -item.concept_priority,
        ),
    )


def _duration_start(facts: list[SecFact], fiscal_period: str) -> date | None:
    duration_facts = [
        item
        for item in facts
        if item.start is not None and item.canonical_name not in _INSTANT_CONCEPTS
    ]
    anchors = [
        item for item in duration_facts if item.canonical_name in _ANCHOR_CONCEPTS
    ]
    candidates = anchors or duration_facts
    if not candidates:
        return None

    def days(item: SecFact) -> int:
        if item.start is None:
            raise ValueError("duration fact is missing its start date")
        return (item.end - item.start).days + 1

    if fiscal_period == "FY":
        preferred = [item for item in candidates if 250 <= days(item) <= 430]
        pool = preferred or candidates
        return max(pool, key=lambda item: (days(item), item.filed)).start

    quarter = [item for item in candidates if 50 <= days(item) <= 130]
    pool = quarter or candidates
    return min(pool, key=lambda item: (days(item), -item.filed.toordinal())).start


def _coherent_accession(
    facts: list[SecFact], fiscal_period: str
) -> tuple[dict[str, SecFact], date | None]:
    target_start = _duration_start(facts, fiscal_period)
    selected: dict[str, SecFact] = {}
    for canonical_name in _CONCEPTS:
        candidates = [item for item in facts if item.canonical_name == canonical_name]
        if canonical_name not in _INSTANT_CONCEPTS:
            candidates = [item for item in candidates if item.start == target_start]
        if candidates:
            selected[canonical_name] = _best_fact(candidates)
    return selected, target_start


def _periods_from_facts(cik: str, facts: list[SecFact]) -> list[FinancialPeriod]:
    accession_groups: dict[tuple[date, int, str, str], list[SecFact]] = {}
    for fact in facts:
        if fact.fiscal_year is None or fact.fiscal_period is None:
            continue
        fp = fact.fiscal_period
        if fp not in {"FY", "Q1", "Q2", "Q3", "Q4"}:
            continue
        # Company Facts repeats comparative values under a later filing's FY/FP.
        # A real non-calendar fiscal end is at most one calendar year away.
        if abs(fact.end.year - fact.fiscal_year) > 1:
            continue
        base_form = fact.form.removesuffix("/A")
        if fp == "FY" and base_form != "10-K":
            continue
        if fp in {"Q1", "Q2", "Q3"} and base_form != "10-Q":
            continue
        key = (fact.end, fact.fiscal_year, fp, fact.accession_number)
        accession_groups.setdefault(key, []).append(fact)

    logical_groups: dict[
        tuple[date, int, str], list[tuple[dict[str, SecFact], date | None]]
    ] = {}
    for (period_end, fiscal_year, fp, _accession), grouped in accession_groups.items():
        values, target_start = _coherent_accession(grouped, fp)
        if values:
            logical_groups.setdefault((period_end, fiscal_year, fp), []).append(
                (values, target_start)
            )

    periods: list[FinancialPeriod] = []
    for (period_end, fiscal_year, fp), candidates in sorted(logical_groups.items()):
        values, target_start = max(
            candidates,
            key=lambda item: (
                bool(_ANCHOR_CONCEPTS.intersection(item[0])),
                max(fact.filed for fact in item[0].values()),
                any(fact.form.endswith("/A") for fact in item[0].values()),
                len(item[0]),
            ),
        )
        if not any(name in values for name in ("revenue", "net_income", "assets")):
            continue
        source_fact = max(values.values(), key=lambda item: item.filed)
        accession_path = source_fact.accession_number.replace("-", "")
        source_url = AnyHttpUrl(
            "https://www.sec.gov/Archives/edgar/data/" f"{int(cik)}/{accession_path}/"
        )
        normalized_values = {
            name: item.value for name, item in values.items() if name in _CONCEPTS
        }
        fact_sources = {
            name: FinancialFactProvenance(
                concept=item.concept,
                unit=item.unit,
                accession_number=item.accession_number,
                form=item.form,
                filed=item.filed,
                period_start=item.start,
                period_end=item.end,
                frame=item.frame,
            )
            for name, item in values.items()
        }
        periods.append(
            FinancialPeriod.model_validate(
                {
                    "fiscal_year": fiscal_year,
                    "fiscal_period": fp,
                    "period_start": target_start,
                    "period_end": period_end,
                    "currency": "USD",
                    "source_url": source_url,
                    "source_label": (
                        f"SEC {source_fact.form} {source_fact.accession_number}"
                    ),
                    "fact_sources": fact_sources,
                    **normalized_values,
                }
            )
        )
    return periods[-20:]


class SecFundamentalsProvider(StockFundamentalsProvider):
    """Join official SEC identities, submissions, and XBRL facts."""

    def __init__(self, manager: ProviderManager, *, user_agent: str) -> None:
        self._manager = manager
        self._ticker_adapter = SecTickerMapAdapter(user_agent=user_agent)
        self._submissions_adapter = SecSubmissionsAdapter(user_agent=user_agent)
        self._facts_adapter = SecCompanyFactsAdapter(user_agent=user_agent)
        self._outbound_limit = asyncio.Semaphore(2)

    async def _fetch[DataT: BaseModel](
        self,
        adapter: ProviderAdapter[DataT],
        request: ProviderRequest,
    ) -> ProviderResponse[DataT]:
        async with self._outbound_limit:
            return await self._manager.fetch(adapter, request)

    async def fundamentals(
        self, exchange: StockExchange, symbol: str
    ) -> ProviderResponse[StockFundamentalsSnapshot]:
        if exchange not in {StockExchange.NASDAQ, StockExchange.NYSE}:
            raise ResourceNotFoundError(
                "SEC fundamentals apply to supported U.S. exchange identities."
            )
        normalized = symbol.strip().upper()
        ticker_response = await self._fetch(
            self._ticker_adapter,
            ProviderRequest(
                operation="sec.tickers",
                asset=CanonicalAsset(asset_type=AssetType.SYSTEM, key="sec-tickers"),
                soft_ttl_seconds=86_400,
                hard_ttl_seconds=604_800,
            ),
        )
        company = next(
            (
                item
                for item in ticker_response.data.companies
                if item.ticker == normalized
            ),
            None,
        )
        if company is None:
            raise ResourceNotFoundError("The ticker was not found in the SEC mapping.")
        cik = str(company.cik).zfill(10)
        asset = CanonicalAsset(
            asset_type=AssetType.STOCK,
            key=f"{exchange.value}:{normalized}",
            provider_id=cik,
        )
        submissions_response, facts_response = await asyncio.gather(
            self._fetch(
                self._submissions_adapter,
                ProviderRequest(
                    operation="sec.submissions",
                    asset=asset,
                    soft_ttl_seconds=7_200,
                    hard_ttl_seconds=21_600,
                ),
            ),
            self._fetch(
                self._facts_adapter,
                ProviderRequest(
                    operation="sec.company_facts",
                    asset=asset,
                    soft_ttl_seconds=43_200,
                    hard_ttl_seconds=86_400,
                ),
            ),
        )
        periods = _periods_from_facts(cik, facts_response.data.facts)
        if not periods:
            raise ResourceNotFoundError(
                "No supported SEC financial periods were available for this company."
            )
        submissions = submissions_response.data
        warnings = [
            warning.message
            for meta in (submissions_response.meta, facts_response.meta)
            for warning in meta.warnings
        ]
        snapshot = StockFundamentalsSnapshot(
            symbol=normalized,
            exchange=exchange,
            profile=StockProfile(
                symbol=normalized,
                company_name=submissions.name or company.title,
                exchange=exchange,
                currency="USD",
                country="United States",
                industry=submissions.sic_description,
                website=submissions.website,
                provider_id=f"SEC:{cik}",
            ),
            periods=periods,
            reports=submissions.reports,
            source_warnings=warnings,
        )
        metas = [ticker_response.meta, submissions_response.meta, facts_response.meta]
        fetched_at = max(item.fetched_at for item in metas)
        source_times = [
            item.source_timestamp for item in metas if item.source_timestamp
        ]
        digest = hashlib.sha256(
            "".join(item.provenance.raw_payload_sha256 for item in metas).encode()
        ).hexdigest()
        statuses = {item.cache_status for item in metas}
        cache_status = (
            CacheStatus.STALE
            if CacheStatus.STALE in statuses
            else (
                CacheStatus.BYPASS
                if CacheStatus.BYPASS in statuses
                else (
                    CacheStatus.MISS
                    if CacheStatus.MISS in statuses
                    else CacheStatus.HIT
                )
            )
        )
        freshness = (
            Freshness.STALE
            if cache_status is CacheStatus.STALE
            else (
                Freshness.CACHED
                if cache_status is CacheStatus.HIT
                else Freshness.DELAYED
            )
        )
        return ProviderResponse(
            data=snapshot,
            meta=ProviderMeta(
                source=SEC_PROVIDER,
                source_timestamp=max(source_times) if source_times else None,
                fetched_at=fetched_at,
                cache_status=cache_status,
                freshness=freshness,
                staleness_seconds=max(item.staleness_seconds for item in metas),
                partial=bool(warnings),
                warnings=[warning for meta in metas for warning in meta.warnings],
                delay_class=DelayClass.FILING,
                provenance=ProviderProvenance(
                    provider=SEC_PROVIDER,
                    operation="stocks.fundamentals",
                    source_url=submissions_response.meta.provenance.source_url,
                    raw_payload_sha256=digest,
                    schema_version="sec-fundamentals-v1",
                    terms_review_version=SEC_TERMS_REVIEW,
                    attribution=SEC_ATTRIBUTION,
                ),
            ),
        )


__all__ = [
    "SEC_ATTRIBUTION",
    "SEC_PROVIDER",
    "SecCompanyFactsAdapter",
    "SecFacts",
    "SecFundamentalsProvider",
    "SecSubmissions",
    "SecSubmissionsAdapter",
    "SecTickerMap",
    "SecTickerMapAdapter",
]
