"""Chart data -> downloadable Excel bytes. Pure, no streamlit import."""

import io
import re

import pandas as pd

_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _sheet_name(name: str) -> str:
    return _INVALID_SHEET_CHARS.sub("_", name)[:31]


def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """One .xlsx file, one sheet per (name, frame) pair."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=_sheet_name(name), index=False)
    return buffer.getvalue()
