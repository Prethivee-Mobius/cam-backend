from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.schemas import AuditSummaryCards, AuditWidgetItem, AuditWidgetsResponse


def _fmt_currency(amount: float) -> str:
    return f"${amount:,.0f}" if amount == int(amount) else f"${amount:,.2f}"


def _metric_value(rows: list[dict[str, Any]], name: str) -> float | None:
    for row in rows:
        if row.get("Metric") == name:
            val = row.get("Value")
            if val is None or val == "":
                return None
            return float(val)
    return None


def _grand_total_calculated_balance(summary: list[dict[str, Any]]) -> float | None:
    for row in summary:
        category = row.get("category") or row.get("Category")
        if category == "GRAND TOTAL":
            val = row.get("calculated_balance")
            if val is None and "Calculated Balance" in row:
                val = row.get("Calculated Balance")
            return float(val) if val is not None else None
    return None


def build_audit_widgets(
    audit_id: UUID,
    *,
    cam_line_items: list[dict[str, Any]],
    summary_cards: dict[str, Any] | AuditSummaryCards | None,
    audit_control_metrics: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    updated_at: Any,
) -> AuditWidgetsResponse:
    cards = summary_cards or {}
    if isinstance(cards, AuditSummaryCards):
        data = cards.model_dump()
    else:
        data = cards

    total_current = float(data.get("total_current_cam") or 0)
    total_allowable = float(data.get("total_allowable_cam") or 0)
    total_variance = float(data.get("total_variance") or 0)
    category_count = len(cam_line_items)

    base_year = _metric_value(audit_control_metrics, "Base Year")
    base_year_total = _metric_value(audit_control_metrics, "Base Year Total")
    calculated_balance = _grand_total_calculated_balance(summary)

    variance_subtitle = (
        "Over allowable amount"
        if total_variance > 0.01
        else "Within cap" if total_variance < -0.01 else "Matches allowable amount"
    )

    base_year_display = str(int(base_year)) if base_year is not None else "—"
    base_year_total_display = _fmt_currency(base_year_total) if base_year_total is not None else "—"
    calculated_balance_display = (
        _fmt_currency(calculated_balance) if calculated_balance is not None else "—"
    )

    widgets = [
        AuditWidgetItem(
            key="total_current_cam",
            label="Total Current CAM",
            value=total_current,
            display_value=_fmt_currency(total_current),
            subtitle=f"{category_count} expense categor{'y' if category_count == 1 else 'ies'}",
            tone="teal",
        ),
        AuditWidgetItem(
            key="total_allowable_cam",
            label="Total Allowable CAM",
            value=total_allowable,
            display_value=_fmt_currency(total_allowable),
            subtitle="Per lease cap rules",
            tone="green",
        ),
        AuditWidgetItem(
            key="total_variance",
            label="Total Variance",
            value=total_variance,
            display_value=_fmt_currency(total_variance),
            subtitle=variance_subtitle,
            tone="red",
        ),
        AuditWidgetItem(
            key="base_year",
            label="Base Year",
            value=base_year if base_year is not None else 0.0,
            display_value=base_year_display,
            subtitle="Manual entry",
            tone="teal",
        ),
        AuditWidgetItem(
            key="base_year_total",
            label="Base Year Total",
            value=base_year_total if base_year_total is not None else 0.0,
            display_value=base_year_total_display,
            subtitle="Manual entry",
            tone="teal",
        ),
        AuditWidgetItem(
            key="calculated_balance",
            label="Calculated Balance",
            value=calculated_balance if calculated_balance is not None else 0.0,
            display_value=calculated_balance_display,
            subtitle="Grand total reconciliation",
            tone="green",
        ),
    ]

    return AuditWidgetsResponse(
        audit_id=audit_id,
        widgets=widgets,
        updated_at=updated_at,
    )
