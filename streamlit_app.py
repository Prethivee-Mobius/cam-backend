import os
import io
import json
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

# ========================= SETUP & CONFIG =========================
st.set_page_config(page_title="CAM Reconciliation Editor", layout="wide")
load_dotenv()

# Initialize OpenAI Client
api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    client = OpenAI(api_key=api_key)
else:
    st.error("⚠️ OPENAI_API_KEY not found. Please set it in your environment or .env file.")
    st.stop()

# ========================= HELPER FUNCTIONS =========================
def upload_pdf_stream(uploaded_file) -> str:
    file_tuple = (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")
    file_obj = client.files.create(file=file_tuple, purpose="user_data")
    return file_obj.id

def _extract_json_block(content: str):
    content = content.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    return content

# ====================== EXTRACTION LOGIC ======================
FIELD_DEFINITIONS = [
    ("TENANT'S PRORATA SHARE %", "CAM", ["cam prorata share", "pro-rata share cam"]),
    ("TENANT'S PRORATA SHARE %", "TAX", ["tax prorata share", "pro-rata share tax"]),
    ("TENANT'S PRORATA SHARE %", "INSURANCE", ["insurance prorata", "pro-rata share ins"]),
    ("CAP ON CAM %", "CAM", ["cap on cam increase", "cap (if applicable)"]),
    ("TOTAL EXPENSE", "TAX", ["tax expense", "real estate taxes"]),
    ("TOTAL EXPENSE", "INSURANCE", ["insurance expense"]),
    ("PRIOR BILLED AMOUNT", "CAM", ["prior estimates billed", "amount billed"]),
    ("PRIOR BILLED AMOUNT", "TAX", ["prior estimates billed"]),
    ("PRIOR BILLED AMOUNT", "INSURANCE", ["prior estimates billed"]),
    ("BALANCE DUE", "CAM", ["balance due", "net amount due"]),
    ("BALANCE DUE", "TAX", ["balance due"]),
    ("BALANCE DUE", "INSURANCE", ["balance due"]),
]

@st.cache_data(show_spinner=False)
def extract_document_data_stream(lease_file, cam_file):
    lease_id = upload_pdf_stream(lease_file)
    cam_id = upload_pdf_stream(cam_file)

    field_hint_lines = "\n".join(
        f'- field="{name}", category="{cat or "N/A"}" (aliases: {", ".join(aliases)})'
        for name, cat, aliases in FIELD_DEFINITIONS
    )
    
    prompt_metrics = f"""
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
    
    resp_metrics = client.responses.create(
        model="gpt-5.1",
        input=[{"role": "user", "content": [{"type": "input_file", "file_id": cam_id}, {"type": "input_text", "text": prompt_metrics}]}]
    )
    metrics = json.loads(_extract_json_block(resp_metrics.output_text))

    prompt_cam = """
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
    resp_cam = client.responses.create(
        model="gpt-5.1",
        input=[{"role": "user", "content": [{"type": "input_file", "file_id": cam_id}, {"type": "input_text", "text": prompt_cam}]}]
    )
    cam_table = json.loads(_extract_json_block(resp_cam.output_text))

    return metrics, cam_table

# ========================= STREAMLIT UI =========================
st.title("📊 Interactive CAM Reconciliation Summary")
st.write("Upload your documents below to parse metrics, toggle line items, and run auditable CAM calculations in real-time.")

# Sidebar Configuration
with st.sidebar:
    st.header("📂 Document Upload")
    lease_file = st.file_uploader("Upload Lease PDF", type=["pdf"])
    cam_file = st.file_uploader("Upload CAM Reconciliation PDF", type=["pdf"])
    
    st.divider()
    
    if lease_file and cam_file:
        if st.button("🚀 Run Audit Analysis", type="primary", use_container_width=True):
            with st.spinner("Analyzing documents via AI..."):
                try:
                    raw_metrics, raw_cam = extract_document_data_stream(lease_file, cam_file)
                    
                    cam_df = pd.DataFrame(raw_cam)
                    if "Amount" not in cam_df.columns:
                        cam_df["Amount"] = 0.0
                    cam_df["Included in Cap"] = True
                    
                    initial_cam_total = cam_df["Amount"].sum()
                    default_prev_year = initial_cam_total * 0.90
                    
                    metrics_dict = {f"{m['field']} ({m['category']})": m['value'] for m in raw_metrics if m.get('value') is not None}
                    metrics_df = pd.DataFrame([
                        {"Metric": "CAM Pro-Rata (%)", "Value": (metrics_dict.get("TENANT'S PRORATA SHARE % (CAM)") or 100) },
                        {"Metric": "TAX Pro-Rata (%)", "Value": (metrics_dict.get("TENANT'S PRORATA SHARE % (TAX)") or 100) },
                        {"Metric": "INSURANCE Pro-Rata (%)", "Value": (metrics_dict.get("TENANT'S PRORATA SHARE % (INSURANCE)") or 100)},
                        {"Metric": "Cap on CAM (%)", "Value": (metrics_dict.get("CAP ON CAM % (CAM)") or 5.0)}, 
                        {"Metric": "Previous Year Capped CAM Total", "Value": default_prev_year},
                        {"Metric": "TAX Total Expense", "Value": metrics_dict.get("TOTAL EXPENSE (TAX)") or 0.0},
                        {"Metric": "INSURANCE Total Expense", "Value": metrics_dict.get("TOTAL EXPENSE (INSURANCE)") or 0.0},
                        {"Metric": "CAM Prior Billed", "Value": metrics_dict.get("PRIOR BILLED AMOUNT (CAM)") or 0.0},
                        {"Metric": "TAX Prior Billed", "Value": metrics_dict.get("PRIOR BILLED AMOUNT (TAX)") or 0.0},
                        {"Metric": "INSURANCE Prior Billed", "Value": metrics_dict.get("PRIOR BILLED AMOUNT (INSURANCE)") or 0.0},
                        {"Metric": "CAM Stated Balance Due", "Value": metrics_dict.get("BALANCE DUE (CAM)") or 0.0},
                        {"Metric": "TAX Stated Balance Due", "Value": metrics_dict.get("BALANCE DUE (TAX)") or 0.0},
                        {"Metric": "INSURANCE Stated Balance Due", "Value": metrics_dict.get("BALANCE DUE (INSURANCE)") or 0.0},
                    ])
                    
                    st.session_state.cam_df = cam_df
                    st.session_state.metrics_df = metrics_df
                    st.success("Extraction Complete!")
                except Exception as e:
                    st.error(f"Error during extraction: {e}")
    else:
        st.warning("Please upload both required PDFs to activate processing.")

# Check if state data is initialized
if "cam_df" in st.session_state and "metrics_df" in st.session_state:
    
    col1, col2 = st.columns([1.6, 1])

    with col1:
        st.subheader("1. CAM Line Items Expense Ledger")
        st.caption("Modify item costs or untick checkboxes to separate uncapped expenses.")
        
        edited_cam_df = st.data_editor(
            st.session_state.cam_df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Included in Cap": st.column_config.CheckboxColumn("Included in Cap"),
                "Amount": st.column_config.NumberColumn("Amount ($)", format="%.2f")
            }
        )

    with col2:
        st.subheader("2. Audit Control Metrics")
        st.caption("Fine-tune global parameters extracted from documents:")
        
        edited_metrics_df = st.data_editor(
            st.session_state.metrics_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Metric": st.column_config.TextColumn(disabled=True),
                "Value": st.column_config.NumberColumn("Value", format="%.4f")
            }
        )
        
    def get_metric(name, default=0.0):
        val = edited_metrics_df.loc[edited_metrics_df["Metric"] == name, "Value"].values
        return float(val[0]) if len(val) > 0 else default

    st.divider()
    st.subheader("3. Consolidated Reconciliation Worksheet")
    
    # --- CAP CALCULATIONS (Strict Formulas) ---
    actual_capped_total = edited_cam_df.loc[edited_cam_df["Included in Cap"] == True, "Amount"].sum()
    actual_uncapped_total = edited_cam_df.loc[edited_cam_df["Included in Cap"] == False, "Amount"].sum()
    
    cap_pct = get_metric("Cap on CAM (%)", 5.0) / 100.0
    prev_year_capped = get_metric("Previous Year Capped CAM Total")
    
    max_capped_allowed = prev_year_capped * (1 + cap_pct)
    capped_recoverable = min(actual_capped_total, max_capped_allowed)
    uncapped_recoverable = actual_uncapped_total
    total_recoverable = capped_recoverable + uncapped_recoverable
    
    # --- SUMMARY COMPILATION ---
    cam_prorata = get_metric("CAM Pro-Rata (%)") / 100.0
    tax_prorata = get_metric("TAX Pro-Rata (%)") / 100.0
    ins_prorata = get_metric("INSURANCE Pro-Rata (%)") / 100.0

    summary_data = []
    
    tenant_capped_share = capped_recoverable * cam_prorata
    summary_data.append({
        "Category": "CAM - Capped",
        "Actual Property Exp.": actual_capped_total,
        "Recoverable Exp. (Allowed)": capped_recoverable,
        "Pro-Rata (%)": cam_prorata * 100,
        "Tenant Share": tenant_capped_share,
        "Prior Billed (Escrow)": None,
        "Calculated Balance": None,
        "Stated Balance Due": None,
        "Variance": None
    })
    
    tenant_uncapped_share = uncapped_recoverable * cam_prorata
    summary_data.append({
        "Category": "CAM - Uncapped",
        "Actual Property Exp.": actual_uncapped_total,
        "Recoverable Exp. (Allowed)": uncapped_recoverable,
        "Pro-Rata (%)": cam_prorata * 100,
        "Tenant Share": tenant_uncapped_share,
        "Prior Billed (Escrow)": None,
        "Calculated Balance": None,
        "Stated Balance Due": None,
        "Variance": None
    })
    
    tenant_cam_share = total_recoverable * cam_prorata
    cam_billed = get_metric("CAM Prior Billed")
    cam_due = tenant_cam_share - cam_billed
    stated_cam = get_metric("CAM Stated Balance Due")
    summary_data.append({
        "Category": "CAM - TOTAL",
        "Actual Property Exp.": actual_capped_total + actual_uncapped_total,
        "Recoverable Exp. (Allowed)": total_recoverable,
        "Pro-Rata (%)": cam_prorata * 100,
        "Tenant Share": tenant_cam_share,
        "Prior Billed (Escrow)": cam_billed,
        "Calculated Balance": cam_due,
        "Stated Balance Due": stated_cam,
        "Variance": cam_due - stated_cam
    })
    
    tax_exp = get_metric("TAX Total Expense")
    tenant_tax = tax_exp * tax_prorata
    tax_billed = get_metric("TAX Prior Billed")
    tax_stated = get_metric("TAX Stated Balance Due", 0.0)
    tax_due = tenant_tax - tax_billed
    summary_data.append({
        "Category": "TAX",
        "Actual Property Exp.": tax_exp,
        "Recoverable Exp. (Allowed)": tax_exp,
        "Pro-Rata (%)": tax_prorata * 100,
        "Tenant Share": tenant_tax,
        "Prior Billed (Escrow)": tax_billed,
        "Calculated Balance": tax_due,
        "Stated Balance Due": tax_stated,
        "Variance": tax_due - tax_stated
    })
    
    ins_exp = get_metric("INSURANCE Total Expense")
    tenant_ins = ins_exp * ins_prorata
    ins_billed = get_metric("INSURANCE Prior Billed")
    ins_stated = get_metric("INSURANCE Stated Balance Due", 0.0)
    ins_due = tenant_ins - ins_billed
    summary_data.append({
        "Category": "INSURANCE",
        "Actual Property Exp.": ins_exp,
        "Recoverable Exp. (Allowed)": ins_exp,
        "Pro-Rata (%)": ins_prorata * 100,
        "Tenant Share": tenant_ins,
        "Prior Billed (Escrow)": ins_billed,
        "Calculated Balance": ins_due,
        "Stated Balance Due": ins_stated,
        "Variance": ins_due - ins_stated
    })
    
    total_actual_exp = (actual_capped_total + actual_uncapped_total) + tax_exp + ins_exp
    total_recoverable_exp = total_recoverable + tax_exp + ins_exp
    total_tenant_share = tenant_cam_share + tenant_tax + tenant_ins
    total_billed = cam_billed + tax_billed + ins_billed
    total_calc_balance = cam_due + tax_due + ins_due
    total_stated_balance = stated_cam + tax_stated + ins_stated
    
    summary_data.append({
        "Category": "GRAND TOTAL",
        "Actual Property Exp.": total_actual_exp,
        "Recoverable Exp. (Allowed)": total_recoverable_exp,
        "Pro-Rata (%)": None,
        "Tenant Share": total_tenant_share,
        "Prior Billed (Escrow)": total_billed,
        "Calculated Balance": total_calc_balance,
        "Stated Balance Due": total_stated_balance,
        "Variance": total_calc_balance - total_stated_balance
    })
    
    summary_df = pd.DataFrame(summary_data)
    
    st.dataframe(
        summary_df.style.format({
            "Actual Property Exp.": "${:,.2f}",
            "Recoverable Exp. (Allowed)": "${:,.2f}",
            "Pro-Rata (%)": "{:.4f}%",
            "Tenant Share": "${:,.2f}",
            "Prior Billed (Escrow)": "${:,.2f}",
            "Calculated Balance": "${:,.2f}",
            "Stated Balance Due": "${:,.2f}",
            "Variance": "${:,.2f}"
        }, na_rep="-").apply(lambda x: ['background: #e9f5ee; font-weight: bold' if x['Category'] == 'GRAND TOTAL' else '' for i in x], axis=1),
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    # ==============================================================
    # 4. UNIFIED HTML-STYLE AUDIT GRID
    # ==============================================================
    st.subheader("4. Unified CAM Audit Grid")
    st.caption("A combined view of line items and consolidated totals with calculated caps, variances, and tenant shares.")

    unified_rows = []

    # Process Line Items First
    for idx, row in edited_cam_df.iterrows():
        cat = row.get("Category", f"Line Item {idx}")
        current_charge = float(row.get("Amount", 0.0))
        
        prior_amount = current_charge * 0.90
        
        if row.get("Included in Cap", True):
            cap_val = prior_amount * (1 + cap_pct)
            allowed = min(current_charge, cap_val)
            variance = current_charge - allowed 
        else:
            cap_val = current_charge 
            allowed = current_charge
            variance = 0.0
            
        # Line item tenant share calculation based on allowed expense
        tenant_share = allowed * cam_prorata

        unified_rows.append({
            "Type": "Line Item",
            "Description": cat,
            "Current Yr Charge": current_charge,
            "Prior Yr Amount": prior_amount,
            "Cap Value": cap_val,
            "Variance": variance,
            "Pro-Rata (%)": cam_prorata * 100,  # Line items apply the CAM pro-rata
            "Tenant Share": tenant_share
        })

    # Add spacing row
    unified_rows.append({
        "Type": "", "Description": "", "Current Yr Charge": None, "Prior Yr Amount": None, 
        "Cap Value": None, "Variance": None, "Pro-Rata (%)": None, "Tenant Share": None
    })

    # Process Consolidated Summary Rows
    for idx, row in summary_df.iterrows():
        if row["Category"] in ["CAM - Capped", "CAM - Uncapped"]:
            continue
            
        unified_rows.append({
            "Type": "Consolidated Summary",
            "Description": row["Category"],
            "Current Yr Charge": row["Actual Property Exp."],
            "Prior Yr Amount": None, 
            "Cap Value": row["Recoverable Exp. (Allowed)"],
            "Variance": row["Variance"],
            "Pro-Rata (%)": row["Pro-Rata (%)"],
            "Tenant Share": row["Tenant Share"]
        })

    unified_df = pd.DataFrame(unified_rows)

    # Display the unified grid
    st.dataframe(
        unified_df.style.format({
            "Current Yr Charge": "${:,.2f}",
            "Prior Yr Amount": "${:,.2f}",
            "Cap Value": "${:,.2f}",
            "Variance": "${:,.2f}",
            "Pro-Rata (%)": "{:.4f}%",
            "Tenant Share": "${:,.2f}"
        }, na_rep="-").apply(lambda x: ['background: #fdfcf8; font-weight: bold' if x['Type'] == 'Consolidated Summary' else '' for i in x], axis=1),
        use_container_width=True,
        hide_index=True
    )
    
    # --- EXCEL DOWNLOAD LOGIC ---
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        
        summary_df.to_excel(writer, sheet_name='Consolidated Summary', index=False)
        edited_cam_df.to_excel(writer, sheet_name='CAM Line Items', index=False)
        unified_df.to_excel(writer, sheet_name='Unified Audit Grid', index=False)
        edited_metrics_df.to_excel(writer, sheet_name='Audit Metrics', index=False)
        
        df_mapping = {
            'Consolidated Summary': summary_df,
            'CAM Line Items': edited_cam_df,
            'Unified Audit Grid': unified_df,
            'Audit Metrics': edited_metrics_df
        }
        
        for sheet_name, df in df_mapping.items():
            worksheet = writer.sheets[sheet_name]
            for i, col in enumerate(df.columns):
                max_len = df[col].astype(str).str.len().max()
                safe_max_len = int(max_len) if pd.notna(max_len) else 0
                column_len = max(safe_max_len, len(str(col))) + 2
                worksheet.set_column(i, i, column_len)

    download_excel = buffer.getvalue()
    
    st.download_button(
        label="📥 Download Full Reconciliation Workbook (Excel)",
        data=download_excel,
        file_name='Comprehensive_CAM_Reconciliation.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        type="primary"
    )