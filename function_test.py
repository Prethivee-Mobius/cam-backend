import os
import json
import re
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ========================= CONFIG =========================
# LEASE_PDF_PATH = "/home/mob240005747/Documents/CAM/Sample/36025 Lease.pdf"
# CAM_RECON_PDF_PATH = "/home/mob240005747/Documents/CAM/Sample/36025 - Greensboro, NC - 2024 CAM Reconciliation.pdf"

LEASE_PDF_PATH = "/home/mob240005747/Documents/CAM/Sample/14005 EXECUTED SDWeissman - Lease (Birmingham).pdf"
CAM_RECON_PDF_PATH = "/home/mob240005747/Documents/CAM/Sample/14005 - Birmingham, AL - 2024 CAM Reconciliation.pdf"


# Alternative sample:
# CAM_RECON_PDF_PATH = "/home/mob240005747/Documents/CAM/Sample/10121 - Monroe, CT - 2024-2025 CAM Reconciliation.pdf"

OUTPUT_DIR = "cam_verification_direct_birm"
# =========================================================

def ensure_dir(path: str):
    Path(path).mkdir(exist_ok=True)

ensure_dir(OUTPUT_DIR)


def upload_pdf(file_path: str) -> str:
    print(f"Uploading {Path(file_path).name}...")
    with open(file_path, "rb") as f:
        file_obj = client.files.create(file=f, purpose="user_data")
    print(f"✅ Uploaded: {file_obj.id}")
    return file_obj.id


def _extract_json_block(content: str):
    content = content.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    return content


def _to_number(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "not found":
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    is_pct = "%" in s
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", "-", "."):
        return None
    try:
        num = float(s)
    except ValueError:
        return None
    if negative:
        num = -num
    if is_pct:
        num = num / 100.0
    return num


# ====================== KEY METRICS EXTRACTION ======================

FIELD_DEFINITIONS = [
    ("YEAR OF EXPENSES CONSIDERED", None, ["billing period", "operating actuals for", "expense year"]),
    ("TENANT'S GROSS LEASE AREA SQ.FT", None, ["square footage", "tenant's gla", "premises sq ft"]),
    ("TOTAL PROPERTY AREA SQ.FT", None, ["total property sf", "center gla", "total bldg sq ft"]),
    ("TENANT'S PRORATA SHARE %", None, ["tenant's prorata share", "pro-rata share"]),
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


def extract_key_metrics(cam_file_id: str):
    print("\n📊 Extracting Key Metrics (Direct GPT)...")

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
        model="gpt-5.1",   # or "gpt-5.1" if available
        input=[{"role": "user", "content": [
            {"type": "input_file", "file_id": cam_file_id},
            {"type": "input_text", "text": prompt}
        ]}]
    )

    content = _extract_json_block(response.output_text)

    try:
        records = json.loads(content)
        with open(f"{OUTPUT_DIR}/lease_key_metrics.json", "w") as f:
            json.dump(records, f, indent=2)
        print(f"✅ Extracted {len(records)} key metrics.")
        return records
    except Exception as e:
        print("❌ Failed to parse key metrics:", e)
        print("Raw:", content[:500])
        return []


# ====================== CAM TABLE EXTRACTION ======================

def extract_cam_table(cam_file_id: str):
    print("\n📊 Extracting CAM Costs table...")

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
        model="gpt-5.1",
        input=[{"role": "user", "content": [
            {"type": "input_file", "file_id": cam_file_id},
            {"type": "input_text", "text": prompt}
        ]}]
    )

    content = _extract_json_block(response.output_text)

    try:
        cam_table = json.loads(content)
        with open(f"{OUTPUT_DIR}/cam_table_extracted.json", "w") as f:
            json.dump(cam_table, f, indent=2)
        print(f"✅ Extracted {len(cam_table)} CAM items.")
        return cam_table
    except Exception as e:
        print("❌ CAM table parsing failed:", e)
        return []


# ====================== LEASE OPERATING COSTS ======================

def extract_lease_operating_costs(lease_file_id: str):
    print("\n📜 Extracting Lease Operating Costs rules...")

    prompt = """
From the lease document, extract all **included** and **excluded** items under Operating Costs / Common Area Maintenance (CAM).

    Identify the items under Operating Costs / CAM that are explicitly
    INCLUDED (permitted to be charged to the tenant) and the items that are
    explicitly EXCLUDED (not permitted to be charged to the tenant).

    Return ONLY a JSON object with exactly this shape:
    {{
      "included_costs": [
        {{
          "name": "...",                 // the item name/category
          "value": "...",                // the exact text/phrase as it appears in the lease for this item (used later to locate it on the page)
          "page_number": <integer>,      // page number (from nearest "[PAGE N]" marker) where this item appears
          "reason": "..."                // brief note on why it's included, if stated
        }}
      ],
      "excluded_costs": [
        {{
          "name": "...",
          "value": "...",
          "page_number": <integer>,
          "reason": "..."
        }}
      ]
    }}

    The "value" field must be a short, exact, verbatim snippet from the lease
    text (not paraphrased) so it can be searched for on the page later.
    Do not add anything else outside this JSON object.
"""

    response = client.responses.create(
        model="gpt-5.1",
        input=[{"role": "user", "content": [
            {"type": "input_file", "file_id": lease_file_id},
            {"type": "input_text", "text": prompt}
        ]}]
    )

    content = _extract_json_block(response.output_text)

    try:
        lease_costs = json.loads(content)
        lease_costs.setdefault("included_costs", [])
        lease_costs.setdefault("excluded_costs", [])
        with open(f"{OUTPUT_DIR}/lease_operating_costs.json", "w") as f:
            json.dump(lease_costs, f, indent=2)
        print("✅ Lease rules extracted.")
        return lease_costs
    except Exception as e:
        print("❌ Lease costs parsing failed:", e)
        return {"included_costs": [], "excluded_costs": []}


# ====================== COMPARISON ======================

def compare_and_generate_json(cam_table: list, lease_costs: dict):
    print("\n⚖️ Generating final comparison...")

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
        "lease clause name": "copied from the matchine Lease Operating Costs name",
        "page_number": <integer, copied from the matching Lease Operating Costs item>
      }}
    ]

    Rules for setting these fields:
    - If the item matches something in the lease's "excluded_costs" list,
      set "lease_classification" to "Excluded" and "status" to "Discrepancy"
      (it is being billed even though the lease excludes it).
    - If the item matches something in the lease's "included_costs" list,
      set "lease_classification" to "Included" and "status" to "Permitted".
    - If the lease doesn't clearly address this item either way, set
      "lease_classification" to "Not Specified" and "status" to "Ambiguous".
    - "reason" should briefly explain the match (or lack of one) to the
      corresponding lease item.
    """

    response = client.responses.create(
        model="gpt-5.1",
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}]
    )

    content = _extract_json_block(response.output_text)

    try:
        comparison = json.loads(content)
        with open(f"{OUTPUT_DIR}/final_comparison.json", "w") as f:
            json.dump(comparison, f, indent=2)
        print("✅ Final comparison generated.")
        return comparison
    except Exception as e:
        print("❌ Comparison failed:", e)
        return None


# ====================== BBOX ANNOTATION (unchanged) ======================

def _normalize_page_numbers(items: list):
    for item in items:
        pn = item.get("page_number")
        if pn is not None and not isinstance(pn, int):
            try:
                item["page_number"] = int(str(pn).strip())
            except ValueError:
                item["page_number"] = None
    return items


def annotate_outputs_with_bbox(cam_table: list, comparison: list, lease_costs: dict):
    # Import your bbox utility
    from bbox_utils import annotate_items_with_bbox

    if cam_table:
        print("\n📍 Annotating CAM table with bbox...")
        _normalize_page_numbers(cam_table)
        cam_table = annotate_items_with_bbox(
            pdf_path=CAM_RECON_PDF_PATH, items=cam_table,
            value_key="value", page_key="page_number", debug=True
        )
        with open(f"{OUTPUT_DIR}/cam_table_extracted_with_bbox.json", "w") as f:
            json.dump(cam_table, f, indent=2)

    if lease_costs:
        print("\n📍 Annotating lease costs with bbox...")
        for key in ("included_costs", "excluded_costs"):
            items = lease_costs.get(key) or []
            if items:
                _normalize_page_numbers(items)
                lease_costs[key] = annotate_items_with_bbox(
                    pdf_path=LEASE_PDF_PATH, items=items,
                    value_key="value", page_key="page_number", debug=True
                )
        with open(f"{OUTPUT_DIR}/lease_operating_costs_with_bbox.json", "w") as f:
            json.dump(lease_costs, f, indent=2)


# ====================== MAIN ======================

def main():
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY missing")

    lease_id = upload_pdf(LEASE_PDF_PATH)
    cam_id = upload_pdf(CAM_RECON_PDF_PATH)

    # Extract everything directly with GPT
    key_metrics = extract_key_metrics(cam_id)
    cam_table = extract_cam_table(cam_id)
    lease_costs = extract_lease_operating_costs(lease_id)

    comparison = None
    if cam_table and lease_costs:
        comparison = compare_and_generate_json(cam_table, lease_costs)

    # Add bounding boxes
    annotate_outputs_with_bbox(cam_table, comparison, lease_costs)

    print(f"\n🎉 Process completed! Check folder: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()