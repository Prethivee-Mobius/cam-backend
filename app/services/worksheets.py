from __future__ import annotations

from typing import Any

from app.models.schemas import AuditMetrics, SummaryRow

METRIC_FIELD_MAP = {
    "CAM Pro-Rata (%)": "cam_prorata_pct",
    "TAX Pro-Rata (%)": "tax_prorata_pct",
    "INSURANCE Pro-Rata (%)": "insurance_prorata_pct",
    "Cap on CAM (%)": "cap_on_cam_pct",
    "Previous Year Capped CAM Total": "previous_year_capped_cam_total",
    "TAX Total Expense": "tax_total_expense",
    "INSURANCE Total Expense": "insurance_total_expense",
    "CAM Prior Billed": "cam_prior_billed",
    "TAX Prior Billed": "tax_prior_billed",
    "INSURANCE Prior Billed": "insurance_prior_billed",
    "CAM Stated Balance Due": "cam_stated_balance_due",
    "TAX Stated Balance Due": "tax_stated_balance_due",
    "INSURANCE Stated Balance Due": "insurance_stated_balance_due",
    "Base Year": "base_year",
    "Base Year Total": "base_year_total",
}


def merge_audit_control_metrics(
    existing: list[dict[str, Any]],
    updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_name = {row["Metric"]: row for row in existing}
    for row in updates:
        by_name[row["Metric"]] = row
    order = list(METRIC_FIELD_MAP.keys())
    merged = [by_name[name] for name in order if name in by_name]
    for name, row in by_name.items():
        if name not in order:
            merged.append(row)
    return merged


def parse_audit_control_metrics(
    rows: list[dict[str, Any]],
    fallback: AuditMetrics | None = None,
) -> AuditMetrics:
    data = (fallback or AuditMetrics()).model_dump()
    for row in rows:
        field_name = METRIC_FIELD_MAP.get(row.get("Metric", ""))
        if field_name is None:
            continue
        val = row.get("Value")
        if val is None or val == "":
            if field_name in ("base_year", "base_year_total"):
                data[field_name] = None
            continue
        data[field_name] = float(val)
    return AuditMetrics(**data)


def _grid_row_key(row: dict[str, Any]) -> tuple[str, str]:
    return (row.get("Type") or "", row.get("Description") or "")


def _grid_status(variance: float | None) -> str | None:
    if variance is None:
        return None
    return "pass" if round(float(variance), 2) == 0 else "fail"


def merge_unified_grid_reviewer_comments(
    previous: list[dict[str, Any]],
    updated: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    comments = {
        _grid_row_key(row): row.get("Reviewer Comment") or row.get("reviewer_comment") or ""
        for row in previous
    }
    for row in updated:
        key = _grid_row_key(row)
        if key in comments:
            row["Reviewer Comment"] = comments[key]
        elif "Reviewer Comment" not in row:
            row["Reviewer Comment"] = ""
    return updated


def apply_unified_grid_reviewer_comments(
    grid: list[dict[str, Any]],
    updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    comments = {
        _grid_row_key(row): row.get("Reviewer Comment") or row.get("reviewer_comment") or ""
        for row in updates
    }
    result: list[dict[str, Any]] = []
    for row in grid:
        merged = dict(row)
        key = _grid_row_key(merged)
        if key in comments:
            merged["Reviewer Comment"] = comments[key]
        result.append(merged)
    return result


def ensure_control_metric_rows(
    rows: list[dict[str, Any]],
    metrics: AuditMetrics,
) -> list[dict[str, Any]]:
    by_name = {row["Metric"]: row for row in rows}
    merged: list[dict[str, Any]] = []
    for template in build_audit_control_metrics(metrics):
        merged.append(by_name.get(template["Metric"], template))
    return merged


def build_audit_control_metrics(metrics: AuditMetrics) -> list[dict[str, Any]]:
    return [
        {"Metric": "CAM Pro-Rata (%)", "Value": metrics.cam_prorata_pct},
        {"Metric": "TAX Pro-Rata (%)", "Value": metrics.tax_prorata_pct},
        {"Metric": "INSURANCE Pro-Rata (%)", "Value": metrics.insurance_prorata_pct},
        {"Metric": "Cap on CAM (%)", "Value": metrics.cap_on_cam_pct},
        {"Metric": "Previous Year Capped CAM Total", "Value": metrics.previous_year_capped_cam_total},
        {"Metric": "TAX Total Expense", "Value": metrics.tax_total_expense},
        {"Metric": "INSURANCE Total Expense", "Value": metrics.insurance_total_expense},
        {"Metric": "CAM Prior Billed", "Value": metrics.cam_prior_billed},
        {"Metric": "TAX Prior Billed", "Value": metrics.tax_prior_billed},
        {"Metric": "INSURANCE Prior Billed", "Value": metrics.insurance_prior_billed},
        {"Metric": "CAM Stated Balance Due", "Value": metrics.cam_stated_balance_due},
        {"Metric": "TAX Stated Balance Due", "Value": metrics.tax_stated_balance_due},
        {"Metric": "INSURANCE Stated Balance Due", "Value": metrics.insurance_stated_balance_due},
        {"Metric": "Base Year", "Value": metrics.base_year},
        {"Metric": "Base Year Total", "Value": metrics.base_year_total},
    ]


def build_unified_audit_grid(
    cam_line_items: list[dict[str, Any]],
    metrics: AuditMetrics,
    summary: list[SummaryRow],
) -> list[dict[str, Any]]:
    cap_pct = metrics.cap_on_cam_pct / 100.0
    cam_prorata = metrics.cam_prorata_pct / 100.0
    rows: list[dict[str, Any]] = []

    for idx, item in enumerate(cam_line_items):
        category = item.get("Category") or item.get("category") or f"Line Item {idx + 1}"
        current_charge = float(item.get("Amount", 0.0) or 0.0)
        prior_amount = current_charge * 0.90
        included_in_cap = item.get("Included in Cap", item.get("Included_in_Cap", True))

        if included_in_cap:
            cap_val = prior_amount * (1 + cap_pct)
            allowed = min(current_charge, cap_val)
            variance = current_charge - allowed
        else:
            cap_val = current_charge
            allowed = current_charge
            variance = 0.0

        tenant_share = allowed * cam_prorata
        rows.append(
            {
                "Type": "Line Item",
                "Description": category,
                "Current Yr Charge": round(current_charge, 2),
                "Prior Yr Amount": round(prior_amount, 2),
                "Cap Value": round(cap_val, 2),
                "Variance": round(variance, 2),
                "Pro-Rata (%)": round(cam_prorata * 100, 4),
                "Tenant Share": round(tenant_share, 2),
                "Lease Page": item.get("Lease Page"),
                "clause_pdfCoordinates": item.get("clause_pdfCoordinates"),
                "Status": _grid_status(round(variance, 2)),
                "Reviewer Comment": "",
            }
        )

    rows.append(
        {
            "Type": "",
            "Description": "",
            "Current Yr Charge": None,
            "Prior Yr Amount": None,
            "Cap Value": None,
            "Variance": None,
            "Pro-Rata (%)": None,
            "Tenant Share": None,
            "Lease Page": None,
            "clause_pdfCoordinates": None,
            "Status": None,
            "Reviewer Comment": "",
        }
    )

    for row in summary:
        if row.category in {"CAM - Capped", "CAM - Uncapped"}:
            continue
        variance = row.variance
        rows.append(
            {
                "Type": "Consolidated Summary",
                "Description": row.category,
                "Current Yr Charge": row.actual_property_exp,
                "Prior Yr Amount": None,
                "Cap Value": row.recoverable_exp_allowed,
                "Variance": variance,
                "Pro-Rata (%)": row.prorata_pct,
                "Tenant Share": row.tenant_share,
                "Lease Page": None,
                "clause_pdfCoordinates": None,
                "Status": _grid_status(variance),
                "Reviewer Comment": "",
            }
        )

    return rows
