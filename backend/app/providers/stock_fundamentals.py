"""Normalized, traceable official-report fundamentals.

SEC filings are fetched from the regulator at runtime. PSX/company-report data
is loaded from a versioned manifest and is deliberately fail closed: a company
is publishable only after a named human reviewer records all required checks.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.app.cache import CacheStatus
from backend.app.core.exceptions import ResourceNotFoundError
from backend.app.providers.models import (
    DelayClass,
    Freshness,
    ProviderMeta,
    ProviderProvenance,
    ProviderResponse,
)
from backend.app.providers.stocks import StockExchange, StockProfile


class _FundamentalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class StockDataMode(StrEnum):
    """Stable values displayed by the four-mode stock source legend."""

    LICENSED_PROVIDER = "licensed_provider"
    USER_SUPPLIED = "user_supplied"
    OFFICIAL_REPORTS = "official_reports"
    OFFLINE_DEMO = "offline_demo"


class FundamentalModel(StrEnum):
    """Select calculations that are meaningful for the company's sector."""

    CORPORATE = "corporate"
    BANK = "bank"


class ReportingBasis(StrEnum):
    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"


class PublicationStatus(StrEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"


class FactReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    HUMAN_VERIFIED = "human_verified"


class FinancialFactProvenance(_FundamentalModel):
    """SEC XBRL field evidence used to build one normalized period."""

    source_kind: Literal["sec_xbrl"] = "sec_xbrl"
    concept: str = Field(min_length=1, max_length=160)
    unit: str = Field(min_length=1, max_length=40)
    accession_number: str = Field(min_length=1, max_length=40)
    form: str = Field(min_length=1, max_length=20)
    filed: date
    period_start: date | None = None
    period_end: date
    frame: str | None = Field(default=None, max_length=40)


class OfficialReportFactProvenance(_FundamentalModel):
    """Trace a normalized value back to a report, page, label, and unit."""

    source_kind: Literal["official_report"] = "official_report"
    report_id: str = Field(min_length=1, max_length=160)
    document_page: int = Field(ge=1, le=10_000)
    printed_page: str | None = Field(default=None, min_length=1, max_length=30)
    source_table: str = Field(min_length=1, max_length=200)
    reported_label: str = Field(min_length=1, max_length=200)
    reported_value: Decimal
    reported_unit: str = Field(min_length=1, max_length=20)
    unit_scale: int = Field(ge=1, le=1_000_000_000)
    reporting_basis: ReportingBasis
    extraction_method: Literal["machine_extracted", "manual_transcription"]
    review_status: FactReviewStatus = FactReviewStatus.UNREVIEWED

    @field_validator("reported_unit")
    @classmethod
    def normalize_reported_unit(cls, value: str) -> str:
        return value.strip().upper()


FinancialFactEvidence = Annotated[
    FinancialFactProvenance | OfficialReportFactProvenance,
    Field(discriminator="source_kind"),
]


class FinancialPeriod(_FundamentalModel):
    fiscal_year: int = Field(ge=1900, le=2200)
    fiscal_period: str = Field(pattern=r"^(FY|Q[1-4]|H[12]|9M)$")
    period_start: date | None = None
    period_end: date
    currency: str = Field(min_length=3, max_length=3)
    reporting_basis: ReportingBasis | None = None
    reported_unit_scale: int = Field(default=1, ge=1, le=1_000_000_000)

    # General-company values are normalized to base currency units.
    revenue: Decimal | None = None
    cost_of_revenue: Decimal | None = None
    gross_profit: Decimal | None = None
    operating_profit: Decimal | None = None
    net_income: Decimal | None = None
    eps: Decimal | None = None
    assets: Decimal | None = Field(default=None, ge=0)
    current_assets: Decimal | None = Field(default=None, ge=0)
    liabilities: Decimal | None = Field(default=None, ge=0)
    current_liabilities: Decimal | None = Field(default=None, ge=0)
    equity: Decimal | None = None
    debt: Decimal | None = Field(default=None, ge=0)
    cash: Decimal | None = Field(default=None, ge=0)
    operating_cash_flow: Decimal | None = None
    investing_cash_flow: Decimal | None = None
    financing_cash_flow: Decimal | None = None

    # Banking fields avoid treating deposits as ordinary corporate debt or
    # applying a current ratio to a bank.
    profit_return_earned: Decimal | None = None
    profit_return_expensed: Decimal | None = None
    net_profit_return: Decimal | None = None
    total_income: Decimal | None = None
    operating_expenses: Decimal | None = None
    profit_before_tax: Decimal | None = None
    deposits: Decimal | None = Field(default=None, ge=0)
    financing_and_advances: Decimal | None = Field(default=None, ge=0)
    investments: Decimal | None = Field(default=None, ge=0)
    capital_adequacy_ratio_percent: Decimal | None = Field(default=None, ge=0)
    non_performing_financing_ratio_percent: Decimal | None = Field(default=None, ge=0)

    source_url: AnyHttpUrl
    source_label: str = Field(min_length=1, max_length=200)
    fact_sources: dict[str, FinancialFactEvidence] = Field(
        default_factory=dict,
        max_length=50,
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_period_dates(self) -> Self:
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        return self


class CompanyReport(_FundamentalModel):
    report_id: str = Field(min_length=1, max_length=160)
    report_type: str = Field(pattern=r"^(annual|quarterly|announcement|10-K|10-Q|8-K)$")
    title: str = Field(min_length=1, max_length=300)
    published_at: date | None = None
    publication_period: str | None = Field(
        default=None,
        pattern=r"^\d{4}(?:-(?:0[1-9]|1[0-2]))?$",
    )
    approved_at: date | None = None
    period_end: date | None = None
    source_url: AnyHttpUrl
    source_name: str = Field(min_length=1, max_length=120)
    accession_number: str | None = Field(default=None, max_length=40)
    amended: bool = False
    reporting_basis: ReportingBasis | None = None
    document_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-fA-F0-9]{64}$",
    )
    document_page_count: int | None = Field(default=None, ge=1, le=10_000)

    @model_validator(mode="after")
    def require_publication_evidence(self) -> Self:
        if self.published_at is None and self.publication_period is None:
            raise ValueError("published_at or publication_period is required")
        return self


class StockFundamentalsSnapshot(_FundamentalModel):
    symbol: str = Field(min_length=1, max_length=12)
    exchange: StockExchange
    profile: StockProfile
    fundamental_model: FundamentalModel = FundamentalModel.CORPORATE
    periods: list[FinancialPeriod] = Field(max_length=40)
    reports: list[CompanyReport] = Field(min_length=1, max_length=100)
    source_warnings: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_identity_and_periods(self) -> Self:
        if (
            self.profile.symbol != self.symbol
            or self.profile.exchange is not self.exchange
        ):
            raise ValueError("profile identity must match the fundamentals identity")
        period_keys = [
            (item.fiscal_year, item.fiscal_period, item.reporting_basis)
            for item in self.periods
        ]
        if len(period_keys) != len(set(period_keys)):
            raise ValueError("duplicate financial period and reporting basis")
        report_ids = [item.report_id for item in self.reports]
        if len(report_ids) != len(set(report_ids)):
            raise ValueError("duplicate report_id")
        return self


class ManifestReview(_FundamentalModel):
    """A human-controlled publication gate; machines cannot self-approve."""

    status: PublicationStatus = PublicationStatus.CANDIDATE
    human_reviewer: str | None = Field(default=None, min_length=2, max_length=120)
    reviewed_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2_000)
    source_identity_checked: bool = False
    statement_basis_checked: bool = False
    figures_checked: bool = False
    unit_conversion_checked: bool = False
    accounting_checks_checked: bool = False

    @model_validator(mode="after")
    def enforce_human_approval(self) -> Self:
        checks = (
            self.source_identity_checked,
            self.statement_basis_checked,
            self.figures_checked,
            self.unit_conversion_checked,
            self.accounting_checks_checked,
        )
        if self.status is PublicationStatus.APPROVED:
            if (
                self.human_reviewer is None
                or self.reviewed_at is None
                or not all(checks)
            ):
                raise ValueError(
                    "approved publication requires a named human reviewer, a "
                    "review timestamp, and every review check"
                )
            if self.reviewed_at.tzinfo is None:
                raise ValueError("reviewed_at must include a timezone")
        elif self.human_reviewer is not None or self.reviewed_at is not None:
            raise ValueError(
                "candidate/rejected entries must not claim a completed human review"
            )
        return self


class OfficialReportManifestCompany(_FundamentalModel):
    review: ManifestReview
    fundamentals: StockFundamentalsSnapshot


_FINANCIAL_FIELDS = frozenset(
    {
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "operating_profit",
        "net_income",
        "eps",
        "assets",
        "current_assets",
        "liabilities",
        "current_liabilities",
        "equity",
        "debt",
        "cash",
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "profit_return_earned",
        "profit_return_expensed",
        "net_profit_return",
        "total_income",
        "operating_expenses",
        "profit_before_tax",
        "deposits",
        "financing_and_advances",
        "investments",
        "capital_adequacy_ratio_percent",
        "non_performing_financing_ratio_percent",
    }
)


class OfficialReportManifest(_FundamentalModel):
    schema_version: Literal["official-report-manifest-v2"]
    generated_at: datetime
    source_name: str = Field(min_length=1, max_length=120)
    attribution: str = Field(min_length=1, max_length=300)
    terms_review_version: str = Field(min_length=1, max_length=80)
    allowed_source_hosts: list[str] = Field(min_length=1, max_length=50)
    companies: list[OfficialReportManifestCompany] = Field(max_length=1_000)

    @field_validator("generated_at")
    @classmethod
    def require_aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generated_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("allowed_source_hosts")
    @classmethod
    def normalize_allowed_hosts(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            host = value.strip().casefold().rstrip(".")
            if (
                not host
                or "/" in host
                or ":" in host
                or host.startswith(".")
                or host.endswith(".")
            ):
                raise ValueError("allowed_source_hosts must contain hostnames only")
            if host not in normalized:
                normalized.append(host)
        return normalized

    @model_validator(mode="after")
    def validate_publication_manifest(self) -> Self:
        identities: set[tuple[StockExchange, str]] = set()
        allowed_hosts = set(self.allowed_source_hosts)
        for entry in self.companies:
            snapshot = entry.fundamentals
            identity = (snapshot.exchange, snapshot.symbol)
            if identity in identities:
                raise ValueError("duplicate company identity in manifest")
            identities.add(identity)
            report_by_id = {item.report_id: item for item in snapshot.reports}

            for report in snapshot.reports:
                self._require_allowed_https(report.source_url, allowed_hosts)
                if snapshot.exchange is StockExchange.PSX and (
                    report.document_sha256 is None
                    or report.document_page_count is None
                    or report.reporting_basis is None
                ):
                    raise ValueError(
                        "PSX reports require document hash, page count, and basis"
                    )

            for period in snapshot.periods:
                self._require_allowed_https(period.source_url, allowed_hosts)
                if snapshot.exchange is StockExchange.PSX:
                    self._validate_psx_period(entry, period, report_by_id)
                self._validate_accounting_consistency(period)
        return self

    @staticmethod
    def _require_allowed_https(url: AnyHttpUrl, allowed_hosts: set[str]) -> None:
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or parsed.hostname is None:
            raise ValueError("official report sources must use HTTPS")
        host = parsed.hostname.casefold().rstrip(".")
        if host not in allowed_hosts:
            raise ValueError(f"official report source host is not allowed: {host}")

    @staticmethod
    def _validate_psx_period(
        entry: OfficialReportManifestCompany,
        period: FinancialPeriod,
        report_by_id: dict[str, CompanyReport],
    ) -> None:
        snapshot = entry.fundamentals
        if period.reporting_basis is None:
            raise ValueError("PSX periods require consolidated/standalone basis")
        populated = {
            name for name in _FINANCIAL_FIELDS if getattr(period, name) is not None
        }
        missing_evidence = populated - set(period.fact_sources)
        extra_evidence = set(period.fact_sources) - populated
        if missing_evidence:
            raise ValueError(
                "PSX period has values without field evidence: "
                + ", ".join(sorted(missing_evidence))
            )
        if extra_evidence:
            raise ValueError(
                "PSX period has evidence for missing values: "
                + ", ".join(sorted(extra_evidence))
            )
        if snapshot.fundamental_model is FundamentalModel.BANK:
            required = {"assets", "liabilities", "equity", "net_income", "deposits"}
            if not required.issubset(populated):
                raise ValueError("bank periods lack required sector-specific fields")
            if (
                period.current_assets is not None
                or period.current_liabilities is not None
            ):
                raise ValueError("current-ratio inputs are not valid bank metrics")
        elif populated and "revenue" not in populated:
            raise ValueError("corporate periods with facts require revenue")

        for field_name, evidence in period.fact_sources.items():
            if not isinstance(evidence, OfficialReportFactProvenance):
                raise ValueError("PSX manifest facts require official-report evidence")
            report = report_by_id.get(evidence.report_id)
            if report is None:
                raise ValueError("fact evidence references an unknown report_id")
            if str(report.source_url) != str(period.source_url):
                raise ValueError(
                    "period source URL must match its fact evidence report"
                )
            if report.reporting_basis is not period.reporting_basis:
                raise ValueError("report basis must match the financial period")
            if (
                report.document_page_count is not None
                and evidence.document_page > report.document_page_count
            ):
                raise ValueError("fact evidence page exceeds the report page count")
            if evidence.reporting_basis is not period.reporting_basis:
                raise ValueError("fact evidence basis must match the financial period")
            expected = evidence.reported_value * evidence.unit_scale
            if expected != getattr(period, field_name):
                raise ValueError(
                    f"normalized {field_name} does not match reported value and scale"
                )
            if (
                entry.review.status is PublicationStatus.APPROVED
                and evidence.review_status is not FactReviewStatus.HUMAN_VERIFIED
            ):
                raise ValueError(
                    "approved companies require human-verified fact evidence"
                )

    @staticmethod
    def _validate_accounting_consistency(period: FinancialPeriod) -> None:
        if (
            period.assets is not None
            and period.liabilities is not None
            and period.equity is not None
        ):
            difference = abs(period.assets - period.liabilities - period.equity)
            tolerance = max(Decimal("1"), abs(period.assets) * Decimal("0.0005"))
            if difference > tolerance:
                raise ValueError("assets do not reconcile to liabilities plus equity")
        if (
            period.revenue is not None
            and period.cost_of_revenue is not None
            and period.gross_profit is not None
        ):
            difference = abs(
                period.revenue - period.cost_of_revenue - period.gross_profit
            )
            tolerance = max(Decimal("1"), abs(period.revenue) * Decimal("0.0001"))
            if difference > tolerance:
                raise ValueError("gross profit does not reconcile to revenue less cost")


class ManifestPublicationSummary(_FundamentalModel):
    total: int
    approved: int
    candidate: int
    rejected: int
    published_symbols: list[str]
    gated_symbols: list[str]


class StockFundamentalsProvider(ABC):
    """Public regulatory/company-report data independent of quote licensing."""

    @abstractmethod
    async def fundamentals(
        self, exchange: StockExchange, symbol: str
    ) -> ProviderResponse[StockFundamentalsSnapshot]: ...


class CompositeFundamentalsProvider(StockFundamentalsProvider):
    """Try configured official sources without hiding provider failures."""

    def __init__(self, providers: list[StockFundamentalsProvider]) -> None:
        if not providers:
            raise ValueError("At least one fundamentals provider is required.")
        self._providers = list(providers)

    async def fundamentals(
        self, exchange: StockExchange, symbol: str
    ) -> ProviderResponse[StockFundamentalsSnapshot]:
        for provider in self._providers:
            try:
                return await provider.fundamentals(exchange, symbol)
            except ResourceNotFoundError:
                continue
        raise ResourceNotFoundError(
            "Official fundamentals are not available for this company."
        )


def _report_reference_date(report: CompanyReport) -> date:
    return report.published_at or report.approved_at or report.period_end or date.min


class OfficialReportManifestProvider(StockFundamentalsProvider):
    """Serve only human-approved official-report facts from a v2 manifest."""

    def __init__(self, manifest: OfficialReportManifest, *, raw_sha256: str) -> None:
        self._manifest = manifest
        self._raw_sha256 = raw_sha256
        approved_entries = [
            item
            for item in manifest.companies
            if item.review.status is PublicationStatus.APPROVED
        ]
        self._companies = {
            (item.fundamentals.exchange, item.fundamentals.symbol): item.fundamentals
            for item in approved_entries
        }

    @property
    def publication_summary(self) -> ManifestPublicationSummary:
        statuses = [item.review.status for item in self._manifest.companies]
        published = sorted(
            item.fundamentals.symbol
            for item in self._manifest.companies
            if item.review.status is PublicationStatus.APPROVED
        )
        gated = sorted(
            item.fundamentals.symbol
            for item in self._manifest.companies
            if item.review.status is not PublicationStatus.APPROVED
        )
        return ManifestPublicationSummary(
            total=len(statuses),
            approved=statuses.count(PublicationStatus.APPROVED),
            candidate=statuses.count(PublicationStatus.CANDIDATE),
            rejected=statuses.count(PublicationStatus.REJECTED),
            published_symbols=published,
            gated_symbols=gated,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> OfficialReportManifestProvider:
        resolved = Path(path).expanduser().resolve(strict=True)
        if resolved.suffix.casefold() != ".json" or not resolved.is_file():
            raise ValueError("Official report manifest must be an existing JSON file.")
        raw = resolved.read_bytes()
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Official report manifest exceeds 8 MiB.")
        manifest = OfficialReportManifest.model_validate(json.loads(raw))
        return cls(manifest, raw_sha256=hashlib.sha256(raw).hexdigest())

    async def fundamentals(
        self, exchange: StockExchange, symbol: str
    ) -> ProviderResponse[StockFundamentalsSnapshot]:
        normalized = symbol.strip().upper()
        data = self._companies.get((exchange, normalized))
        if data is None:
            raise ResourceNotFoundError(
                "Human-approved official fundamentals are not available for "
                "this company."
            )
        latest_report = max(data.reports, key=_report_reference_date)
        source_date = _report_reference_date(latest_report)
        source_time = datetime.combine(source_date, datetime.min.time(), tzinfo=UTC)
        fetched_at = datetime.now(UTC)
        return ProviderResponse(
            data=data,
            meta=ProviderMeta(
                source=self._manifest.source_name,
                source_timestamp=source_time,
                fetched_at=fetched_at,
                cache_status=CacheStatus.HIT,
                freshness=Freshness.CACHED,
                staleness_seconds=max(
                    0, int((fetched_at - source_time).total_seconds())
                ),
                partial=bool(data.source_warnings),
                warnings=[],
                delay_class=DelayClass.FILING,
                provenance=ProviderProvenance(
                    provider=self._manifest.source_name,
                    operation="stocks.fundamentals",
                    source_url=latest_report.source_url,
                    raw_payload_sha256=self._raw_sha256,
                    schema_version=self._manifest.schema_version,
                    terms_review_version=self._manifest.terms_review_version,
                    attribution=self._manifest.attribution,
                ),
            ),
        )


__all__ = [
    "CompanyReport",
    "CompositeFundamentalsProvider",
    "FactReviewStatus",
    "FinancialFactProvenance",
    "FinancialPeriod",
    "FundamentalModel",
    "ManifestPublicationSummary",
    "ManifestReview",
    "OfficialReportFactProvenance",
    "OfficialReportManifest",
    "OfficialReportManifestCompany",
    "OfficialReportManifestProvider",
    "PublicationStatus",
    "ReportingBasis",
    "StockDataMode",
    "StockFundamentalsProvider",
    "StockFundamentalsSnapshot",
]
