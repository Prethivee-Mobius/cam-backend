from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.config import OPENAI_MODEL
from app.services.extraction import extract_json_block, get_openai_client


def compare_and_generate_json(
    client: OpenAI,
    cam_table: list[dict[str, Any]],
    lease_costs: dict[str, Any],
) -> list[dict[str, Any]]:
    prompt = f"""
    CAM Costs:
    {json.dumps(cam_table, indent=2)}

    Lease Rules:
    {json.dumps(lease_costs, indent=2)}

    For each CAM Cost item, determine whether it matches an item in the lease's "included_costs" or "excluded_costs".

    Return ONLY a valid JSON array:
    [
      {{
        "name": "...",
        "value": "...",
        "status": "Permitted | Discrepancy | Ambiguous",
        "lease_classification": "Included | Excluded | Not Specified",
        "lease clause name": "copied from the matching Lease Operating Costs name",
        "page_number": <integer, copied from the matching Lease Operating Costs item>
      }}
    ]

    Rules:
    - If the item matches something in the lease's "excluded_costs" list,
      set "lease_classification" to "Excluded" and "status" to "Discrepancy".
    - If the item matches something in the lease's "included_costs" list,
      set "lease_classification" to "Included" and "status" to "Permitted".
    - If the lease doesn't clearly address this item either way, set
      "lease_classification" to "Not Specified" and "status" to "Ambiguous".
    - "name" must match the CAM Cost Category exactly.
    - "page_number" must be copied from the matched lease operating cost item, not the CAM statement page.
    """

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
    )
    content = extract_json_block(response.output_text)
    return json.loads(content)


def _lease_items_by_name(lease_costs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for section in ("included_costs", "excluded_costs"):
        for item in lease_costs.get(section) or []:
            name = (item.get("name") or "").strip().lower()
            if name:
                lookup[name] = item
    return lookup


def _match_comparison(cam_category: str, comparison: list[dict[str, Any]]) -> dict[str, Any] | None:
    cat = cam_category.strip().lower()
    for row in comparison:
        if (row.get("name") or "").strip().lower() == cat:
            return row
    for row in comparison:
        name = (row.get("name") or "").strip().lower()
        if name and (name in cat or cat in name):
            return row
    return None


def apply_comparison_to_cam_table(
    cam_table: list[dict[str, Any]],
    comparison: list[dict[str, Any]] | None,
    lease_costs: dict[str, Any],
) -> list[dict[str, Any]]:
    if not comparison:
        return cam_table

    lease_lookup = _lease_items_by_name(lease_costs)

    for item in cam_table:
        category = item.get("Category") or ""
        comp = _match_comparison(category, comparison)
        clause_name = comp.get("lease clause name") if comp else None
        lease_page = comp.get("page_number") if comp else None

        lease_item = None
        if clause_name:
            lease_item = lease_lookup.get(clause_name.strip().lower())

        if lease_page is None and lease_item:
            lease_page = lease_item.get("page_number")

        item["Lease Page"] = lease_page
        item["lease_clause_name"] = clause_name
        item["lease_classification"] = comp.get("lease_classification") if comp else None
        item["comparison_status"] = comp.get("status") if comp else None
        item["clause_pdfCoordinates"] = lease_item.get("pdfCoordinates") if lease_item else None

    return cam_table


def merge_lease_clause_fields(
    previous_items: list[dict[str, Any]],
    updated_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prev_by_category = {(i.get("Category") or "").strip().lower(): i for i in previous_items}
    clause_keys = (
        "Lease Page",
        "lease_clause_name",
        "lease_classification",
        "comparison_status",
        "clause_pdfCoordinates",
    )
    for item in updated_items:
        prev = prev_by_category.get((item.get("Category") or "").strip().lower())
        if not prev:
            continue
        for key in clause_keys:
            if key not in item or item.get(key) is None:
                item[key] = prev.get(key)
    return updated_items


def run_cam_lease_comparison(
    cam_table: list[dict[str, Any]],
    lease_costs: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    if not cam_table or not lease_costs:
        return cam_table, None
    client = get_openai_client()
    comparison = compare_and_generate_json(client, cam_table, lease_costs)
    enriched = apply_comparison_to_cam_table(cam_table, comparison, lease_costs)
    return enriched, comparison
