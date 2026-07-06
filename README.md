# CAM Reconciliation Backend

FastAPI backend for CAM (Common Area Maintenance) reconciliation audits. It combines:

- **Document extraction** from lease and CAM reconciliation PDFs (OpenAI)
- **Reconciliation calculations** with CAM caps, pro-rata shares, tax/insurance totals, and variance analysis
- **Excel export** of audit worksheets

## Frontend (React)

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) — starts on the **Jobs** page. Upload PDFs to queue a job; when status is **Completed**, click the row to open the reconciliation worksheets.

Run both backend and frontend:

```bash
# terminal 1
uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend && npm run dev
```

## Setup

```bash
cd cam_backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set OPENAI_API_KEY
```

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open API docs at [http://localhost:8000/docs](http://localhost:8000/docs).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/jobs` | Upload PDFs → queue background extraction job |
| GET | `/api/v1/jobs` | List all jobs with status |
| GET | `/api/v1/jobs/{job_id}` | Get job status (pending / running / completed / failed) |
| POST | `/api/v1/audits/extract` | Upload lease + CAM PDFs, extract synchronously |
| POST | `/api/v1/audits/{audit_id}/calculate` | Recalculate with edited line items and metrics |
| GET | `/api/v1/audits/{audit_id}` | Get full audit state |
| GET | `/api/v1/audits/{audit_id}/workspace` | Get data formatted for the audit workspace UI |
| GET | `/api/v1/audits/{audit_id}/export` | Download Unified CAM Audit Grid Excel |
| PUT | `/api/v1/audits/{audit_id}/worksheets` | Update tab 1 and/or tab 2 → recalculates tab 3 |
| PUT | `/api/v1/audits/{audit_id}/worksheets/cam-line-items` | Edit tab 1 → recalculates tab 3 |
| PUT | `/api/v1/audits/{audit_id}/worksheets/audit-control-metrics` | Edit tab 2 → recalculates tab 3 |
| GET | `/api/v1/audits/{audit_id}/worksheets` | All 3 worksheet tabs in one response |
| GET | `/api/v1/audits/{audit_id}/worksheets/audit-control-metrics` | Tab 2: Audit Control Metrics |
| GET | `/api/v1/audits/{audit_id}/worksheets/unified-audit-grid` | Tab 3: Unified CAM Audit Grid |
| GET | `/api/v1/audits/{audit_id}/worksheets/unified-audit-grid/export` | Export Unified CAM Audit Grid to Excel |
| GET | `/api/v1/audits/{audit_id}/lease-operating-costs` | Lease included/excluded costs with `pdfCoordinates` |
| GET | `/api/v1/audits/{audit_id}/cam-line-items` | CAM table line items with `pdfCoordinates` |
| POST | `/api/v1/documents/lease/operating-costs` | Upload lease PDF → operating costs JSON with coordinates |
| POST | `/api/v1/documents/cam/table` | Upload CAM PDF → CAM line items JSON with coordinates |
| PATCH | `/api/v1/audits/{audit_id}/status` | Update audit status |

## Extract lease operating costs only

```bash
curl -X POST "http://localhost:8000/api/v1/documents/lease/operating-costs" \
  -F "lease_pdf=@/path/to/lease.pdf"
```

Returns `included_costs` and `excluded_costs` arrays. Each item includes `name`, `value`, `page_number`, `reason`, and `pdfCoordinates` (or `null` if text could not be located in the PDF).

## Extract CAM table only

```bash
curl -X POST "http://localhost:8000/api/v1/documents/cam/table" \
  -F "cam_pdf=@/path/to/cam_reconciliation.pdf"
```

Returns an array of `{Category, Amount, value, page_number, pdfCoordinates}` objects.

After a full audit extract, you can also fetch stored results:

```bash
curl "http://localhost:8000/api/v1/audits/{audit_id}/lease-operating-costs"
curl "http://localhost:8000/api/v1/audits/{audit_id}/cam-line-items"
```

Coordinates are resolved with PyMuPDF text search (`bbox_utils`).

## Worksheet tabs (Streamlit tables)

Three tabs matching `streamlit_app.py`:

```bash
# All tabs at once
curl "http://localhost:8000/api/v1/audits/{audit_id}/worksheets"

# Individual tabs
curl "http://localhost:8000/api/v1/audits/{audit_id}/worksheets/cam-line-items"
curl "http://localhost:8000/api/v1/audits/{audit_id}/worksheets/audit-control-metrics"
curl "http://localhost:8000/api/v1/audits/{audit_id}/worksheets/unified-audit-grid"

# Export Unified CAM Audit Grid to Excel
curl -OJ "http://localhost:8000/api/v1/audits/{audit_id}/worksheets/unified-audit-grid/export"
```

Recalculate after editing tab 1 and/or tab 2 (tab 3 updates automatically):

```bash
# Edit tab 1 only — change Amount or Included in Cap
curl -X PUT "http://localhost:8000/api/v1/audits/{audit_id}/worksheets/cam-line-items" \
  -H "Content-Type: application/json" \
  -d '{
    "rows": [
      {"Category": "CLEANING", "Amount": 6000, "Included in Cap": true},
      {"Category": "UTILITIES", "Amount": 82735.26, "Included in Cap": false}
    ]
  }'

# Edit tab 2 only — change pro-rata, cap %, prior billed, etc.
curl -X PUT "http://localhost:8000/api/v1/audits/{audit_id}/worksheets/audit-control-metrics" \
  -H "Content-Type: application/json" \
  -d '{
    "rows": [
      {"Metric": "CAM Pro-Rata (%)", "Value": 12.5},
      {"Metric": "Cap on CAM (%)", "Value": 5.0},
      {"Metric": "Previous Year Capped CAM Total", "Value": 45000}
    ]
  }'

# Edit both tabs at once
curl -X PUT "http://localhost:8000/api/v1/audits/{audit_id}/worksheets" \
  -H "Content-Type: application/json" \
  -d '{
    "cam_line_items": [{"Category": "CLEANING", "Amount": 6000, "Included in Cap": true}],
    "audit_control_metrics": [{"Metric": "CAM Pro-Rata (%)", "Value": 12.5}]
  }'
```

Each PUT returns all three tabs; `unified_audit_grid` reflects the latest edits. Tab 3 is read-only (GET only).

Legacy recalculate endpoint (also supported):

## Extract documents

```bash
curl -X POST "http://localhost:8000/api/v1/audits/extract" \
  -F "lease_pdf=@/path/to/lease.pdf" \
  -F "cam_pdf=@/path/to/cam_reconciliation.pdf"
```

Returns an `audit_id` plus extracted key metrics, CAM line items, lease operating costs, and default audit metrics.

## Recalculate

```bash
curl -X POST "http://localhost:8000/api/v1/audits/{audit_id}/calculate" \
  -H "Content-Type: application/json" \
  -d '{
    "cam_line_items": [{"Category": "Landscaping", "Amount": 48200, "Included in Cap": true}],
    "metrics": {
      "cam_prorata_pct": 12.5,
      "tax_prorata_pct": 12.5,
      "insurance_prorata_pct": 12.5,
      "cap_on_cam_pct": 5.0,
      "previous_year_capped_cam_total": 45000,
      "tax_total_expense": 64500,
      "insurance_total_expense": 22300,
      "cam_prior_billed": 10000,
      "tax_prior_billed": 8000,
      "insurance_prior_billed": 2500,
      "cam_stated_balance_due": 500,
      "tax_stated_balance_due": 200,
      "insurance_stated_balance_due": 100
    }
  }'
```

## Project structure

```
app/
├── main.py              # FastAPI app entry point
├── config.py            # Environment configuration
├── models/schemas.py    # Pydantic request/response models
├── routers/
│   ├── audits.py        # Extract, calculate, export endpoints
│   ├── documents.py     # Standalone lease/CAM extraction endpoints
│   └── workspace.py     # Frontend workspace payload
└── services/
    ├── extraction.py    # PDF upload + OpenAI extraction
    ├── bbox_utils.py    # PyMuPDF text search for coordinates
    ├── bbox.py          # Lease/CAM bbox annotation helpers
    ├── calculations.py  # CAM cap & reconciliation engine
    ├── export.py        # Excel workbook generation
    ├── files.py         # PDF file persistence
    └── store.py         # In-memory audit session store
```

## Notes

- Audit sessions are stored in memory and reset when the server restarts.
- Extraction uses the OpenAI Responses API with PDF file input (same approach as `function_test.py` and `streamlit_app.py`).
- Calculations mirror the Streamlit app's cap logic and produce CAM grid rows compatible with `sample.html`.
