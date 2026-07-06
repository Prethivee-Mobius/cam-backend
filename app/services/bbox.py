from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.bbox_utils import annotate_items_with_bbox


def _annotate_single_item(pdf_path: str, item: dict[str, Any], keys: list[str]) -> None:
    for key in keys:
        if item.get("pdfCoordinates") is not None:
            return
        search_item = {
            "value": item.get(key),
            "page_number": item.get("page_number"),
        }
        if search_item["value"] is None or str(search_item["value"]).strip() == "":
            continue
        annotate_items_with_bbox(pdf_path, [search_item], value_key="value")
        if search_item.get("pdfCoordinates"):
            item["pdfCoordinates"] = search_item["pdfCoordinates"]
            if search_item.get("page_number"):
                item["page_number"] = search_item["page_number"]
            return
    item.setdefault("pdfCoordinates", None)


def annotate_lease_operating_costs(pdf_path: str, lease_costs: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(lease_costs)
    for section in ("included_costs", "excluded_costs"):
        items = result.get(section, [])
        annotate_items_with_bbox(pdf_path, items, value_key="value")
        for item in items:
            if item.get("pdfCoordinates") is None:
                _annotate_single_item(pdf_path, item, ["name"])
            item.setdefault("pdfCoordinates", None)
    return result


def annotate_cam_table(pdf_path: str, cam_table: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = deepcopy(cam_table)
    annotate_items_with_bbox(pdf_path, result, value_key="value")
    for item in result:
        if item.get("pdfCoordinates") is None:
            _annotate_single_item(pdf_path, item, ["Amount", "Category"])
        item.setdefault("pdfCoordinates", None)
    return result
