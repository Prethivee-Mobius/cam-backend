from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.schemas import AuditMetrics
from app.services.calculations import run_reconciliation
from app.services.store import audit_store
from app.services.comparison import merge_lease_clause_fields
from app.services.worksheets import (
    apply_unified_grid_reviewer_comments,
    build_audit_control_metrics,
    ensure_control_metric_rows,
    merge_audit_control_metrics,
    merge_unified_grid_reviewer_comments,
    parse_audit_control_metrics,
)


def persist_calculation(
    audit_id: UUID,
    calc: dict[str, Any],
    *,
    cam_line_items: list[dict[str, Any]] | None = None,
    metrics: AuditMetrics | None = None,
    audit_control_metrics: list[dict[str, Any]] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "summary": [row.model_dump() for row in calc["summary"]],
        "unified_grid": [row.model_dump() for row in calc["unified_grid"]],
        "cam_grid": [row.model_dump(by_alias=False) for row in calc["cam_grid"]],
        "exceptions": [row.model_dump() for row in calc["exceptions"]],
        "summary_cards": calc["summary_cards"].model_dump(),
        "unified_audit_grid": calc["unified_audit_grid"],
    }
    if cam_line_items is not None:
        payload["cam_line_items"] = cam_line_items
    if metrics is not None:
        payload["metrics"] = metrics.model_dump()
    if audit_control_metrics is not None:
        payload["audit_control_metrics"] = audit_control_metrics
    else:
        payload["audit_control_metrics"] = calc["audit_control_metrics"]

    audit_store.update(audit_id, **payload)


def recalculate_worksheets(
    audit_id: UUID,
    *,
    cam_line_items: list[dict[str, Any]] | None = None,
    audit_control_metrics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    record = audit_store.get(audit_id)
    if not record:
        raise ValueError("Audit not found")

    items = cam_line_items if cam_line_items is not None else record.cam_line_items
    if cam_line_items is not None and record.cam_line_items:
        items = merge_lease_clause_fields(record.cam_line_items, items)
    current_metrics = AuditMetrics(**record.metrics)

    if audit_control_metrics is not None:
        existing = ensure_control_metric_rows(
            record.audit_control_metrics or build_audit_control_metrics(current_metrics),
            current_metrics,
        )
        control_rows = merge_audit_control_metrics(existing, audit_control_metrics)
        metrics = parse_audit_control_metrics(control_rows, current_metrics)
    else:
        metrics = current_metrics
        control_rows = ensure_control_metric_rows(
            record.audit_control_metrics or build_audit_control_metrics(metrics),
            metrics,
        )

    calc = run_reconciliation(items, metrics, record.clauses)
    calc["audit_control_metrics"] = control_rows
    if record.unified_audit_grid:
        calc["unified_audit_grid"] = merge_unified_grid_reviewer_comments(
            record.unified_audit_grid,
            calc["unified_audit_grid"],
        )

    persist_calculation(
        audit_id,
        calc,
        cam_line_items=items,
        metrics=metrics,
        audit_control_metrics=control_rows,
    )

    return calc


def save_unified_grid_reviewer_comments(
    audit_id: UUID,
    updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    record = audit_store.get(audit_id)
    if not record:
        raise ValueError("Audit not found")
    if not record.unified_audit_grid:
        recalculate_worksheets(audit_id)
        record = audit_store.get(audit_id)
        if not record:
            raise ValueError("Audit not found")

    grid = apply_unified_grid_reviewer_comments(record.unified_audit_grid, updates)
    audit_store.update(audit_id, unified_audit_grid=grid)
    return grid
