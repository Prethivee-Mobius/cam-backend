from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.services.bbox import annotate_cam_table, annotate_lease_operating_costs
from app.services.files import save_pdf

FIELD_DEFINITIONS = [
    ("YEAR OF EXPENSES CONSIDERED", None, ["billing period", "operating actuals for", "expense year"]),
    ("TENANT'S GROSS LEASE AREA SQ.FT", None, ["square footage", "tenant's gla", "premises sq ft"]),
    ("TOTAL PROPERTY AREA SQ.FT", None, ["total property sf", "center gla", "total bldg sq ft"]),
    ("TENANT'S PRORATA SHARE %", "CAM", ["cam prorata share", "pro-rata share cam"]),
    ("TENANT'S PRORATA SHARE %", "TAX", ["tax prorata share", "pro-rata share tax"]),
    ("TENANT'S PRORATA SHARE %", "INSURANCE", ["insurance prorata", "pro-rata share ins"]),
    ("TENANT'S PRORATA SHARE %", "N/A", ["tenant's prorata share", "general pro-rata share"]),
    ("CAP ON CAM %", "CAM", ["cap on cam increase", "cap (if applicable)"]),
    ("TOTAL EXPENSE", "CAM", ["cam expense", "cam subtotal", "operating expenses"]),
    ("TOTAL EXPENSE", "TAX", ["tax expense", "real estate taxes"]),
    ("TOTAL EXPENSE", "INSURANCE", ["insurance expense"]),
    ("PRIOR BILLED AMOUNT", "CAM", ["prior estimates billed", "amount billed"]),
    ("PRIOR BILLED AMOUNT", "TAX", ["prior estimates billed"]),
    ("PRIOR BILLED AMOUNT", "INSURANCE", ["prior estimates billed"]),
    ("BALANCE DUE", "CAM", ["balance due", "net amount due"]),
    ("BALANCE DUE", "TAX", ["balance due"]),
    ("BALANCE DUE", "INSURANCE", ["balance due"]),
]


def get_openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=OPENAI_API_KEY)


def extract_json_block(content: str) -> str:
    content = content.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    return content


def upload_pdf_bytes(client: OpenAI, filename: str, content: bytes) -> str:
    file_obj = client.files.create(file=(filename, content, "application/pdf"), purpose="user_data")
    return file_obj.id


def extract_key_metrics(client: OpenAI, cam_file_id: str) -> list[dict[str, Any]]:
    field_hint_lines = "\n".join(
        f'- field="{name}", category="{cat or "N/A"}" (aliases: {", ".join(aliases)})'
        for name, cat, aliases in FIELD_DEFINITIONS
    )
    prompt = f"""
You are extracting reconciliation metrics from a CAM/Tax/Insurance reconciliation.
Extract values for these fields:
{field_hint_lines}
Return ONLY a valid JSON array. Each element must have this exact shape:
{{
  "field": "<field name exactly as listed>",
  "category": "CAM" | "TAX" | "INSURANCE" | "N/A",
  "value": <numeric value as int/float or null if not found>,
  "page_number": <int or null>
}}
Rules:
- Emit one record per (field, category) pair.
- If single combined reconciliation → use it for CAM and set TAX/INSURANCE to null.
- Never invent numbers. Use null if missing.
"""
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "file_id": cam_file_id},
                    {"type": "input_text", "text": prompt},
                ],
            }
        ],
    )
    content = extract_json_block(response.output_text)
    return json.loads(content)


def extract_cam_table(client: OpenAI, cam_file_id: str) -> list[dict[str, Any]]:
    prompt = """
Extract the main **CAM Costs** table (Common Area Maintenance / Operating Expenses).
Return ONLY a JSON array of line items (exclude grand totals if possible).

Each object:
{
  "Category": "string",
  "Amount": number,
  "value": "exact text as appears in document",
  "page_number": integer
}
"""
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "file_id": cam_file_id},
                    {"type": "input_text", "text": prompt},
                ],
            }
        ],
    )
    content = extract_json_block(response.output_text)
    return json.loads(content)


def extract_lease_operating_costs(client: OpenAI, lease_file_id: str) -> dict[str, Any]:
    prompt = """
From the lease document, extract all **included** and **excluded** items under Operating Costs / Common Area Maintenance (CAM).

Identify items explicitly INCLUDED (permitted to be charged) and EXCLUDED (not permitted).
Explicitly calculate the page number from the start of the document, do not give the page number under that page.
Return ONLY a JSON object with exactly this shape:
{
  "included_costs": [
    {
      "name": "...",
      "value": "...",
      "page_number": 1,
      "reason": "..."
    }
  ],
  "excluded_costs": [
    {
      "name": "...",
      "value": "...",
      "page_number": 1,
      "reason": "..."
    }
  ]
}

The "value" field must be a short, exact, verbatim snippet from the lease text (not paraphrased).
"""
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "file_id": lease_file_id},
                    {"type": "input_text", "text": prompt},
                ],
            }
        ],
    )
    content = extract_json_block(response.output_text)
    return json.loads(content)


def metrics_from_key_metrics(raw_metrics: list[dict[str, Any]], cam_table: list[dict[str, Any]]) -> dict[str, float]:
    metrics_dict = {
        f"{m['field']} ({m['category']})": m.get("value")
        for m in raw_metrics
        if m.get("value") is not None
    }
    initial_cam_total = sum(float(i.get("Amount", 0.0) or 0.0) for i in cam_table)
    default_prev_year = initial_cam_total * 0.90 if initial_cam_total else 0.0

    return {
        "cam_prorata_pct": float(metrics_dict.get("TENANT'S PRORATA SHARE % (CAM)") or 100),
        "tax_prorata_pct": float(metrics_dict.get("TENANT'S PRORATA SHARE % (TAX)") or 100),
        "insurance_prorata_pct": float(metrics_dict.get("TENANT'S PRORATA SHARE % (INSURANCE)") or 100),
        "cap_on_cam_pct": float(metrics_dict.get("CAP ON CAM % (CAM)") or 5.0),
        "previous_year_capped_cam_total": default_prev_year,
        "tax_total_expense": float(metrics_dict.get("TOTAL EXPENSE (TAX)") or 0.0),
        "insurance_total_expense": float(metrics_dict.get("TOTAL EXPENSE (INSURANCE)") or 0.0),
        "cam_prior_billed": float(metrics_dict.get("PRIOR BILLED AMOUNT (CAM)") or 0.0),
        "tax_prior_billed": float(metrics_dict.get("PRIOR BILLED AMOUNT (TAX)") or 0.0),
        "insurance_prior_billed": float(metrics_dict.get("PRIOR BILLED AMOUNT (INSURANCE)") or 0.0),
        "cam_stated_balance_due": float(metrics_dict.get("BALANCE DUE (CAM)") or 0.0),
        "tax_stated_balance_due": float(metrics_dict.get("BALANCE DUE (TAX)") or 0.0),
        "insurance_stated_balance_due": float(metrics_dict.get("BALANCE DUE (INSURANCE)") or 0.0),
    }


def lease_costs_to_clauses(lease_costs: dict[str, Any]) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    idx = 1

    for item in lease_costs.get("included_costs", []):
        clauses.append(
            {
                "id": f"c{idx}",
                "title": f"Included — {item.get('name', 'Operating Cost')}",
                "text": item.get("value") or item.get("reason") or item.get("name", ""),
                "page": item.get("page_number"),
                "confidence": 0.9,
                "source": "Lease PDF",
            }
        )
        idx += 1

    for item in lease_costs.get("excluded_costs", []):
        clauses.append(
            {
                "id": f"c{idx}",
                "title": f"Excluded — {item.get('name', 'Operating Cost')}",
                "text": item.get("value") or item.get("reason") or item.get("name", ""),
                "page": item.get("page_number"),
                "confidence": 0.88,
                "source": "Lease PDF",
            }
        )
        idx += 1

    return clauses


def extract_lease_only(lease_bytes: bytes, lease_filename: str) -> dict[str, Any]:
    client = get_openai_client()
    lease_path = save_pdf(lease_bytes, lease_filename)
    lease_id = upload_pdf_bytes(client, lease_filename, lease_bytes)
    lease_costs = extract_lease_operating_costs(client, lease_id)
    lease_costs = annotate_lease_operating_costs(str(lease_path), lease_costs)
    return {
        "lease_operating_costs": lease_costs,
        "lease_pdf_path": str(lease_path),
    }


def extract_cam_only(cam_bytes: bytes, cam_filename: str) -> dict[str, Any]:
    client = get_openai_client()
    cam_path = save_pdf(cam_bytes, cam_filename)
    cam_id = upload_pdf_bytes(client, cam_filename, cam_bytes)
    cam_table = extract_cam_table(client, cam_id)
    cam_table = annotate_cam_table(str(cam_path), cam_table)
    for item in cam_table:
        item.setdefault("Included in Cap", True)
    return {
        "cam_line_items": cam_table,
        "cam_pdf_path": str(cam_path),
    }


def extract_documents(lease_bytes: bytes, lease_filename: str, cam_bytes: bytes, cam_filename: str) -> dict[str, Any]:
    client = get_openai_client()
    audit_dir = uuid4().hex
    lease_path = save_pdf(lease_bytes, lease_filename, subdir=audit_dir)
    cam_path = save_pdf(cam_bytes, cam_filename, subdir=audit_dir)

    lease_id = upload_pdf_bytes(client, lease_filename, lease_bytes)
    cam_id = upload_pdf_bytes(client, cam_filename, cam_bytes)

    key_metrics = extract_key_metrics(client, cam_id)
    cam_table = extract_cam_table(client, cam_id)
    lease_costs = extract_lease_operating_costs(client, lease_id)

    lease_costs = annotate_lease_operating_costs(str(lease_path), lease_costs)
    cam_table = annotate_cam_table(str(cam_path), cam_table)

    from app.services.comparison import run_cam_lease_comparison

    cam_table, cam_comparison = run_cam_lease_comparison(cam_table, lease_costs)

    metrics = metrics_from_key_metrics(key_metrics, cam_table)
    clauses = lease_costs_to_clauses(lease_costs)

    for item in cam_table:
        item.setdefault("Included in Cap", True)

    return {
        "key_metrics": key_metrics,
        "cam_line_items": cam_table,
        "cam_comparison": cam_comparison,
        "lease_operating_costs": lease_costs,
        "clauses": clauses,
        "metrics": metrics,
        "lease_pdf_path": str(lease_path),
        "cam_pdf_path": str(cam_path),
    }
