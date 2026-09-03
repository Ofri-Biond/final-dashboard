"""Row 1: the four headline KPI cards with prior-period deltas and monthly
sparklines. All numbers come from lib.aggregate.summarize/monthly -- this module
only formats and lays out.
"""

import pandas as pd
import streamlit as st

from lib.aggregate import monthly, summarize
from lib.filters import FilterState

# (label, measure, value_col, sparkline chart_type)
_CARDS = [
    ("Deals", "count", None, "bar"),
    ("Total disclosed value", "sum", "total_musd", "area"),
    ("Median deal size", "median", "total_musd", "line"),
    ("Median upfront", "median", "upfront_musd", "line"),
]


def _format(value: float | None, value_col: str | None) -> str:
    if value is None:
        return "not disclosed"
    return f"{value:,.0f}" if value_col is None else f"${value:,.0f}M"


def _delta(current: float | None, previous: float | None) -> str | None:
    if current is None or previous is None or previous == 0:
        return None
    return f"{(current - previous) / previous * 100:+.1f}%"


def render_kpis(df: pd.DataFrame, prev_df: pd.DataFrame | None, filters: FilterState) -> None:
    for column, (label, measure, value_col, chart_type) in zip(st.columns(4), _CARDS, strict=True):
        with column:
            current = summarize(df, measure, value_col, exclude_mega=filters.exclude_mega_deals)
            previous = (
                summarize(prev_df, measure, value_col, exclude_mega=filters.exclude_mega_deals)
                if prev_df is not None
                else None
            )
            spark = monthly(df, measure, value_col, exclude_mega=filters.exclude_mega_deals)

            st.metric(
                label,
                _format(current.value, value_col),
                delta=_delta(current.value, previous.value if previous else None),
                border=True,
                chart_data=spark.frame["value"].tolist(),
                chart_type=chart_type,
            )
            if value_col is not None:
                st.caption(current.coverage.note())
