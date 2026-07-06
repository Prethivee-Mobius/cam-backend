from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditStatus(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class PdfCoordinates(BaseModel):
    page: int
    page_width: float
    page_height: float
    x0: float
    y0: float
    x1: float
    y1: float


class KeyMetric(BaseModel):
    field: str
    category: str
    value: Optional[float] = None
    page_number: Optional[int] = None


class CamLineItem(BaseModel):
    Category: str
    Amount: float = 0.0
    value: Optional[str] = None
    page_number: Optional[int] = None
    pdfCoordinates: Optional[PdfCoordinates] = None
    Lease_Page: Optional[int] = Field(default=None, alias="Lease Page")
    lease_clause_name: Optional[str] = None
    lease_classification: Optional[str] = None
    comparison_status: Optional[str] = None
    clause_pdfCoordinates: Optional[PdfCoordinates] = None
    Included_in_Cap: bool = Field(default=True, alias="Included in Cap")

    model_config = {"populate_by_name": True}


class CamTableItem(BaseModel):
    Category: str
    Amount: float = 0.0
    value: Optional[str] = None
    page_number: Optional[int] = None
    pdfCoordinates: Optional[PdfCoordinates] = None


class LeaseCostItem(BaseModel):
    name: str
    value: Optional[str] = None
    page_number: Optional[int] = None
    reason: Optional[str] = None
    pdfCoordinates: Optional[PdfCoordinates] = None


class LeaseOperatingCosts(BaseModel):
    included_costs: list[LeaseCostItem] = Field(default_factory=list)
    excluded_costs: list[LeaseCostItem] = Field(default_factory=list)


class AuditMetrics(BaseModel):
    cam_prorata_pct: float = 100.0
    tax_prorata_pct: float = 100.0
    insurance_prorata_pct: float = 100.0
    cap_on_cam_pct: float = 5.0
    previous_year_capped_cam_total: float = 0.0
    tax_total_expense: float = 0.0
    insurance_total_expense: float = 0.0
    cam_prior_billed: float = 0.0
    tax_prior_billed: float = 0.0
    insurance_prior_billed: float = 0.0
    cam_stated_balance_due: float = 0.0
    tax_stated_balance_due: float = 0.0
    insurance_stated_balance_due: float = 0.0
    base_year: Optional[float] = None
    base_year_total: Optional[float] = None


class CalculationStep(BaseModel):
    label: str
    val: str


class CalculationHistoryItem(BaseModel):
    type: str
    text: str
    time: str


class CamGridRow(BaseModel):
    id: str
    category: str
    current: float
    prior: Optional[float] = None
    clause_id: Optional[str] = None
    cap_type: str
    cap_value: Optional[float] = None
    allowed: Optional[float] = None
    status: str
    comment: str = ""
    steps: list[CalculationStep] = Field(default_factory=list)
    source: str = ""
    history: list[CalculationHistoryItem] = Field(default_factory=list)


class Clause(BaseModel):
    id: str
    title: str
    text: str
    page: Optional[int] = None
    confidence: float = 0.85
    source: str = "Lease PDF"


class SummaryRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str = Field(serialization_alias="Category")
    actual_property_exp: Optional[float] = Field(default=None, serialization_alias="Actual Property Exp.")
    recoverable_exp_allowed: Optional[float] = Field(default=None, serialization_alias="Recoverable Exp. (Allowed)")
    prorata_pct: Optional[float] = Field(default=None, serialization_alias="Pro-Rata (%)")
    tenant_share: Optional[float] = Field(default=None, serialization_alias="Tenant Share")
    prior_billed_escrow: Optional[float] = Field(default=None, serialization_alias="Prior Billed (Escrow)")
    calculated_balance: Optional[float] = Field(default=None, serialization_alias="Calculated Balance")
    stated_balance_due: Optional[float] = Field(default=None, serialization_alias="Stated Balance Due")
    variance: Optional[float] = Field(default=None, serialization_alias="Variance")


class UnifiedGridRow(BaseModel):
    type: str
    description: str
    current_yr_charge: Optional[float] = None
    prior_yr_amount: Optional[float] = None
    cap_value: Optional[float] = None
    variance: Optional[float] = None
    prorata_pct: Optional[float] = None
    tenant_share: Optional[float] = None


class AuditControlMetricRow(BaseModel):
    Metric: str
    Value: Optional[float] = None


class UnifiedAuditGridRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    Type: str = ""
    Description: str = ""
    current_yr_charge: Optional[float] = Field(default=None, alias="Current Yr Charge")
    prior_yr_amount: Optional[float] = Field(default=None, alias="Prior Yr Amount")
    cap_value: Optional[float] = Field(default=None, alias="Cap Value")
    Variance: Optional[float] = None
    prorata_pct: Optional[float] = Field(default=None, alias="Pro-Rata (%)")
    tenant_share: Optional[float] = Field(default=None, alias="Tenant Share")
    lease_page: Optional[int] = Field(default=None, alias="Lease Page")
    clause_pdfCoordinates: Optional[PdfCoordinates] = None
    Status: Optional[str] = None
    reviewer_comment: Optional[str] = Field(default=None, alias="Reviewer Comment")


class UnifiedAuditGridReviewRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    Type: str = ""
    Description: str = ""
    reviewer_comment: Optional[str] = Field(default=None, alias="Reviewer Comment")


class UnifiedAuditGridReviewUpdateRequest(BaseModel):
    rows: list[UnifiedAuditGridReviewRow]


class WorksheetsResponse(BaseModel):
    audit_id: UUID
    cam_line_items: list[CamLineItem]
    audit_control_metrics: list[AuditControlMetricRow]
    unified_audit_grid: list[UnifiedAuditGridRow]
    consolidated_summary: list[SummaryRow] = Field(default_factory=list)


class ConsolidatedSummaryResponse(BaseModel):
    audit_id: UUID
    title: str = "Consolidated Reconciliation Worksheet"
    rows: list[SummaryRow]


class CamLineItemsLedgerResponse(BaseModel):
    audit_id: UUID
    title: str = "CAM Line Items Expense Ledger"
    rows: list[CamLineItem]


class AuditControlMetricsResponse(BaseModel):
    audit_id: UUID
    title: str = "Audit Control Metrics"
    rows: list[AuditControlMetricRow]


class UnifiedAuditGridResponse(BaseModel):
    audit_id: UUID
    title: str = "Unified CAM Audit Grid"
    rows: list[UnifiedAuditGridRow]


class ExceptionItem(BaseModel):
    id: str
    row_id: Optional[str] = None
    category: str
    severity: str
    issue: str
    variance: float
    clause_ref: str
    recommendation: str
    status: str = "open"


class AuditSummaryCards(BaseModel):
    total_current_cam: float
    total_allowable_cam: float
    total_variance: float
    exception_count: int
    open_exception_count: int
    high_severity_count: int
    audit_completion_pct: int


class AuditWidgetItem(BaseModel):
    key: str
    label: str
    value: float
    display_value: str
    subtitle: str
    tone: str = "teal"
    show_progress: bool = False
    progress_pct: Optional[int] = None


class AuditWidgetsResponse(BaseModel):
    audit_id: UUID
    widgets: list[AuditWidgetItem]
    updated_at: datetime


class ExtractResponse(BaseModel):
    audit_id: UUID
    key_metrics: list[KeyMetric]
    cam_line_items: list[CamLineItem]
    lease_operating_costs: LeaseOperatingCosts
    clauses: list[Clause]
    metrics: AuditMetrics
    status: AuditStatus = AuditStatus.DRAFT


class WorksheetsUpdateRequest(BaseModel):
    cam_line_items: Optional[list[CamLineItem]] = None
    audit_control_metrics: Optional[list[AuditControlMetricRow]] = None


class CamLineItemsUpdateRequest(BaseModel):
    rows: list[CamLineItem]


class AuditControlMetricsUpdateRequest(BaseModel):
    rows: list[AuditControlMetricRow]


class CalculateRequest(BaseModel):
    cam_line_items: Optional[list[CamLineItem]] = None
    metrics: Optional[AuditMetrics] = None
    audit_control_metrics: Optional[list[AuditControlMetricRow]] = None


class CalculateResponse(BaseModel):
    audit_id: UUID
    cam_line_items: list[CamLineItem]
    audit_control_metrics: list[AuditControlMetricRow]
    unified_audit_grid: list[UnifiedAuditGridRow]
    summary: list[SummaryRow]
    exceptions: list[ExceptionItem]
    summary_cards: AuditSummaryCards


class AuditDetailResponse(BaseModel):
    audit_id: UUID
    status: AuditStatus
    created_at: datetime
    updated_at: datetime
    key_metrics: list[KeyMetric]
    cam_line_items: list[CamLineItem]
    lease_operating_costs: LeaseOperatingCosts
    clauses: list[Clause]
    metrics: AuditMetrics
    audit_control_metrics: list[AuditControlMetricRow] = Field(default_factory=list)
    unified_audit_grid: list[UnifiedAuditGridRow] = Field(default_factory=list)
    summary: list[SummaryRow] = Field(default_factory=list)
    unified_grid: list[UnifiedGridRow] = Field(default_factory=list)
    cam_grid: list[CamGridRow] = Field(default_factory=list)
    exceptions: list[ExceptionItem] = Field(default_factory=list)
    summary_cards: Optional[AuditSummaryCards] = None


class HealthResponse(BaseModel):
    status: str
    openai_configured: bool


class ErrorResponse(BaseModel):
    detail: str


class JobStatusEnum(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobResponse(BaseModel):
    job_id: UUID
    status: JobStatusEnum
    audit_id: Optional[UUID] = None
    lease_filename: str
    cam_filename: str
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    lease_prop_name: str = ""
    tenant_name: str = ""
    lease_id: str = ""


class JobCreateResponse(BaseModel):
    job_id: UUID
    status: JobStatusEnum
    message: str = "Job queued for processing"
    lease_prop_name: str = ""
    tenant_name: str = ""
    lease_id: str = ""
