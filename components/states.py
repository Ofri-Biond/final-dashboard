"""Shared rendering primitives: plotting, empty state, coverage/finding captions,
and the raw-data preview frame. Kept tiny and generic so sections.py composes
them rather than repeating st.plotly_chart/st.caption boilerplate at each call site.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from assets.theme import PLOTLY_CONFIG
from lib.aggregate import Coverage
from lib.export import to_excel_bytes
from lib.filters import FilterState


def plot(fig: go.Figure, key: str) -> None:
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=key)


def finding(sentence: str) -> None:
    st.markdown(f"**{sentence}**")


def download_button(sheets: dict[str, pd.DataFrame], filename: str, key: str) -> None:
    """A small Excel-export affordance for a chart's underlying data, one sheet
    per frame in `sheets` (e.g. {"Deal count": ..., "Disclosed value": ...}).
    """
    st.download_button(
        "Export",
        data=to_excel_bytes(sheets),
        file_name=f"{filename}.xlsx",
        icon=":material/download:",
        key=f"{key}_xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def coverage_caption(coverage: Coverage) -> None:
    st.caption(coverage.note())


def clear_filters() -> None:
    """Reset every filter widget to FilterState()'s defaults, in both session_state
    (the widget values) and the URL (bind="query-params" mirrors session_state
    there) -- then rerun. Shared by the sidebar's Clear button and empty_state's.
    """
    for key in FilterState.__dataclass_fields__:
        st.session_state.pop(key, None)
        st.query_params.pop(key, None)
    st.rerun()


def empty_state(culprits: list[str]) -> None:
    culprit_text = " and ".join(culprits) if culprits else "the current filters"
    st.info(f"No deals match {culprit_text}. Try clearing a filter.")
    if st.button("Clear filters", key="empty_state_clear"):
        clear_filters()


def display_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Display copy where undisclosed money is a "not disclosed" chip, never 0/blank."""
    display = df.copy()
    for col in ("upfront_musd", "total_musd"):
        if col in display.columns:
            display[col] = display[col].apply(
                lambda v: "not disclosed" if pd.isna(v) else f"${v:,.0f}M"
            )
    return display
