from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd


def build_unified_audit_grid_excel(unified_audit_grid: list[dict[str, Any]]) -> bytes:
    """Export only the Unified CAM Audit Grid worksheet (matches Streamlit download)."""
    unified_df = pd.DataFrame(unified_audit_grid)

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        unified_df.to_excel(writer, sheet_name="Unified Audit Grid", index=False)
        worksheet = writer.sheets["Unified Audit Grid"]
        for i, col in enumerate(unified_df.columns):
            max_len = unified_df[col].astype(str).str.len().max()
            safe_max_len = int(max_len) if pd.notna(max_len) else 0
            column_len = max(safe_max_len, len(str(col))) + 2
            worksheet.set_column(i, i, column_len)

    return buffer.getvalue()
