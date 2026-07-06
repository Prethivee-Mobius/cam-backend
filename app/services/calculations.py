from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.schemas import (
    AuditMetrics,
    AuditSummaryCards,
    CamGridRow,
    CalculationHistoryItem,
    CalculationStep,
    ExceptionItem,
    SummaryRow,
    UnifiedGridRow,
)
from app.services.worksheets import build_audit_control_metrics, build_unified_audit_grid


def _fmt_currency(value: float) -> str:
    neg = value < 0
    formatted = f"${abs(value):,.2f}"
    return f"-{formatted}" if neg else formatted


def _row_status(current: float, allowed: float | None, included_in_cap: bool) -> str:
    if allowed is None:
        return "fail"
    variance = current - allowed
    if abs(variance) < 0.01:
        return "pass"
    if not included_in_cap:
        return "pass"
    if variance > 0:
        ratio = variance / max(current, 1)
        return "warn" if ratio <= 0.05 else "fail"
    return "pass"


def _build_exception(row: CamGridRow, cap_pct: float) -> ExceptionItem | None:
    if row.status == "pass":
        return None

    variance = (row.current - row.allowed) if row.allowed is not None else row.current
    if abs(variance) < 0.01 and row.status != "fail":
        return None

    severity = "high" if row.status == "fail" and (row.allowed is None or variance > 1000) else "medium"
    clause_ref = row.clause_id or "No clause matched"

    if row.allowed is None:
        issue = (
            f"{row.category} charge of {_fmt_currency(row.current)} could not be validated "
            "because no governing lease clause was matched."
        )
        recommendation = (
            "Request supporting documentation from the landlord to classify this charge "
            "before it can be validated."
        )
    elif variance > 0:
        issue = (
            f"{row.category} charge of {_fmt_currency(row.current)} exceeds the allowable "
            f"amount of {_fmt_currency(row.allowed)} under lease cap rules ({row.cap_type})."
        )
        recommendation = (
            f"Request landlord apply the {cap_pct:.1f}% controllable expense cap or provide "
            "documentation justifying the overage."
        )
    else:
        return None

    return ExceptionItem(
        id=f"e-{row.id}",
        row_id=row.id,
        category=row.category,
        severity=severity,
        issue=issue,
        variance=round(abs(variance), 2),
        clause_ref=clause_ref,
        recommendation=recommendation,
        status="open",
    )


def run_reconciliation(
    cam_line_items: list[dict[str, Any]],
    metrics: AuditMetrics,
    clauses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cap_pct = metrics.cap_on_cam_pct / 100.0
    prev_year_capped = metrics.previous_year_capped_cam_total
    cam_prorata = metrics.cam_prorata_pct / 100.0
    tax_prorata = metrics.tax_prorata_pct / 100.0
    ins_prorata = metrics.insurance_prorata_pct / 100.0

    actual_capped_total = 0.0
    actual_uncapped_total = 0.0
    cam_grid: list[CamGridRow] = []
    unified_grid: list[UnifiedGridRow] = []

    for idx, item in enumerate(cam_line_items):
        category = item.get("Category") or item.get("category") or f"Line Item {idx + 1}"
        current_charge = float(item.get("Amount", 0.0) or 0.0)
        included_in_cap = item.get("Included in Cap", item.get("Included_in_Cap", True))
        page_number = item.get("page_number")
        source_text = item.get("value") or f"CAM Statement: {category}"

        prior_amount = current_charge * 0.90
        clause_id = clauses[idx]["id"] if clauses and idx < len(clauses) else None

        if included_in_cap:
            actual_capped_total += current_charge
            cap_value = prior_amount * (1 + cap_pct)
            allowed = min(current_charge, cap_value)
            cap_type = f"Percentage ({metrics.cap_on_cam_pct:.0f}%)"
            variance = current_charge - allowed
            steps = [
                CalculationStep(label="Prior Year Amount", val=_fmt_currency(prior_amount)),
                CalculationStep(label="Cap Rate Applied", val=f"× {1 + cap_pct:.2f}"),
                CalculationStep(label="Allowable Ceiling", val=_fmt_currency(cap_value)),
                CalculationStep(label="Current Year Charge", val=_fmt_currency(current_charge)),
                CalculationStep(
                    label="Variance (Charge − Allowed)",
                    val=_fmt_currency(variance) + (" over cap" if variance > 0 else " — within cap"),
                ),
            ]
        else:
            actual_uncapped_total += current_charge
            cap_value = current_charge
            allowed = current_charge
            cap_type = "None (Uncapped)"
            variance = 0.0
            steps = [
                CalculationStep(label="Lease Provision", val="Uncapped pass-through"),
                CalculationStep(label="Current Year Charge", val=_fmt_currency(current_charge)),
                CalculationStep(label="Allowed Amount", val=_fmt_currency(allowed)),
                CalculationStep(label="Variance", val="$0.00"),
            ]

        status = _row_status(current_charge, allowed, included_in_cap)
        tenant_share = allowed * cam_prorata

        cam_grid.append(
            CamGridRow(
                id=f"r{idx + 1}",
                category=category,
                current=round(current_charge, 2),
                prior=round(prior_amount, 2),
                clause_id=clause_id,
                cap_type=cap_type,
                cap_value=round(cap_value, 2) if cap_value is not None else None,
                allowed=round(allowed, 2),
                status=status,
                source=f"{source_text}" + (f" — page {page_number}" if page_number else ""),
                steps=steps,
                history=[
                    CalculationHistoryItem(
                        type="pass" if status == "pass" else "fail",
                        text=f"<strong>Validation Engine</strong> {'passed' if status == 'pass' else 'flagged'} — {category}",
                        time=datetime.utcnow().strftime("Today, %I:%M %p"),
                    )
                ],
            )
        )

        unified_grid.append(
            UnifiedGridRow(
                type="Line Item",
                description=category,
                current_yr_charge=round(current_charge, 2),
                prior_yr_amount=round(prior_amount, 2),
                cap_value=round(cap_value, 2),
                variance=round(variance, 2),
                prorata_pct=round(cam_prorata * 100, 4),
                tenant_share=round(tenant_share, 2),
            )
        )

    max_capped_allowed = prev_year_capped * (1 + cap_pct)
    capped_recoverable = min(actual_capped_total, max_capped_allowed)
    uncapped_recoverable = actual_uncapped_total
    total_recoverable = capped_recoverable + uncapped_recoverable

    tenant_capped_share = capped_recoverable * cam_prorata
    tenant_uncapped_share = uncapped_recoverable * cam_prorata
    tenant_cam_share = total_recoverable * cam_prorata
    cam_billed = metrics.cam_prior_billed
    cam_due = tenant_cam_share - cam_billed
    stated_cam = metrics.cam_stated_balance_due

    tax_exp = metrics.tax_total_expense
    tenant_tax = tax_exp * tax_prorata
    tax_billed = metrics.tax_prior_billed
    tax_stated = metrics.tax_stated_balance_due
    tax_due = tenant_tax - tax_billed

    ins_exp = metrics.insurance_total_expense
    tenant_ins = ins_exp * ins_prorata
    ins_billed = metrics.insurance_prior_billed
    ins_stated = metrics.insurance_stated_balance_due
    ins_due = tenant_ins - ins_billed

    summary: list[SummaryRow] = [
        SummaryRow(
            category="CAM - Capped",
            actual_property_exp=round(actual_capped_total, 2),
            recoverable_exp_allowed=round(capped_recoverable, 2),
            prorata_pct=round(cam_prorata * 100, 4),
            tenant_share=round(tenant_capped_share, 2),
        ),
        SummaryRow(
            category="CAM - Uncapped",
            actual_property_exp=round(actual_uncapped_total, 2),
            recoverable_exp_allowed=round(uncapped_recoverable, 2),
            prorata_pct=round(cam_prorata * 100, 4),
            tenant_share=round(tenant_uncapped_share, 2),
        ),
        SummaryRow(
            category="CAM - TOTAL",
            actual_property_exp=round(actual_capped_total + actual_uncapped_total, 2),
            recoverable_exp_allowed=round(total_recoverable, 2),
            prorata_pct=round(cam_prorata * 100, 4),
            tenant_share=round(tenant_cam_share, 2),
            prior_billed_escrow=round(cam_billed, 2),
            calculated_balance=round(cam_due, 2),
            stated_balance_due=round(stated_cam, 2),
            variance=round(cam_due - stated_cam, 2),
        ),
        SummaryRow(
            category="TAX",
            actual_property_exp=round(tax_exp, 2),
            recoverable_exp_allowed=round(tax_exp, 2),
            prorata_pct=round(tax_prorata * 100, 4),
            tenant_share=round(tenant_tax, 2),
            prior_billed_escrow=round(tax_billed, 2),
            calculated_balance=round(tax_due, 2),
            stated_balance_due=round(tax_stated, 2),
            variance=round(tax_due - tax_stated, 2),
        ),
        SummaryRow(
            category="INSURANCE",
            actual_property_exp=round(ins_exp, 2),
            recoverable_exp_allowed=round(ins_exp, 2),
            prorata_pct=round(ins_prorata * 100, 4),
            tenant_share=round(tenant_ins, 2),
            prior_billed_escrow=round(ins_billed, 2),
            calculated_balance=round(ins_due, 2),
            stated_balance_due=round(ins_stated, 2),
            variance=round(ins_due - ins_stated, 2),
        ),
    ]

    total_actual_exp = (actual_capped_total + actual_uncapped_total) + tax_exp + ins_exp
    total_recoverable_exp = total_recoverable + tax_exp + ins_exp
    total_tenant_share = tenant_cam_share + tenant_tax + tenant_ins
    total_billed = cam_billed + tax_billed + ins_billed
    total_calc_balance = cam_due + tax_due + ins_due
    total_stated_balance = stated_cam + tax_stated + ins_stated

    summary.append(
        SummaryRow(
            category="GRAND TOTAL",
            actual_property_exp=round(total_actual_exp, 2),
            recoverable_exp_allowed=round(total_recoverable_exp, 2),
            tenant_share=round(total_tenant_share, 2),
            prior_billed_escrow=round(total_billed, 2),
            calculated_balance=round(total_calc_balance, 2),
            stated_balance_due=round(total_stated_balance, 2),
            variance=round(total_calc_balance - total_stated_balance, 2),
        )
    )

    unified_grid.append(
        UnifiedGridRow(
            type="",
            description="",
        )
    )

    for row in summary:
        if row.category in {"CAM - Capped", "CAM - Uncapped"}:
            continue
        unified_grid.append(
            UnifiedGridRow(
                type="Consolidated Summary",
                description=row.category,
                current_yr_charge=row.actual_property_exp,
                cap_value=row.recoverable_exp_allowed,
                variance=row.variance,
                prorata_pct=row.prorata_pct,
                tenant_share=row.tenant_share,
            )
        )

    exceptions: list[ExceptionItem] = []
    for row in cam_grid:
        exc = _build_exception(row, metrics.cap_on_cam_pct)
        if exc:
            exceptions.append(exc)

    grand_variance = summary[-1].variance or 0.0
    if abs(grand_variance) > 0.01:
        exceptions.append(
            ExceptionItem(
                id="e-grand-total",
                category="GRAND TOTAL",
                severity="high" if abs(grand_variance) > 500 else "medium",
                issue=(
                    f"Calculated balance ({_fmt_currency(total_calc_balance)}) differs from stated "
                    f"balance due ({_fmt_currency(total_stated_balance)}) by {_fmt_currency(grand_variance)}."
                ),
                variance=round(abs(grand_variance), 2),
                clause_ref="Reconciliation totals",
                recommendation="Review pro-rata shares, prior billed amounts, and stated balances from the CAM statement.",
                status="open",
            )
        )

    total_current = sum(r.current for r in cam_grid)
    total_allowed = sum(r.allowed or 0 for r in cam_grid)
    total_variance = total_current - total_allowed
    open_exceptions = [e for e in exceptions if e.status == "open"]
    high_severity = [e for e in open_exceptions if e.severity == "high"]
    resolved_ratio = 0 if not exceptions else (len(exceptions) - len(open_exceptions)) / len(exceptions)
    completion = min(95, int(35 + resolved_ratio * 40 + (10 if not open_exceptions else 0)))

    summary_cards = AuditSummaryCards(
        total_current_cam=round(total_current, 2),
        total_allowable_cam=round(total_allowed, 2),
        total_variance=round(total_variance, 2),
        exception_count=len(exceptions),
        open_exception_count=len(open_exceptions),
        high_severity_count=len(high_severity),
        audit_completion_pct=completion,
    )

    audit_control_metrics = build_audit_control_metrics(metrics)
    unified_audit_grid = build_unified_audit_grid(cam_line_items, metrics, summary)

    return {
        "summary": summary,
        "unified_grid": unified_grid,
        "cam_grid": cam_grid,
        "exceptions": exceptions,
        "summary_cards": summary_cards,
        "audit_control_metrics": audit_control_metrics,
        "unified_audit_grid": unified_audit_grid,
    }
