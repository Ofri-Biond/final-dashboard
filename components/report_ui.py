"""Sidebar "Download report" popover: exports the current filtered view as an
.xlsx workbook or a .pdf brief. Rendered from the sidebar rather than a header
row (the dashboard has none) so it stays reachable even when the filtered view
is empty -- app.py calls st.stop() right after this, before KPIs/brief/sections
render, so anything placed in the main-page flow would be unreachable there.

st.download_button needs its file bytes ready before it draws (there's no
lazy/on-click data callback), and this container's body re-executes on every
app rerun regardless of whether the popover is open. Building a multi-
thousand-row Excel workbook or a 9-chart PDF (each kaleido image export costs
real wall-clock time) unconditionally on every rerun would tax every
unrelated interaction elsewhere in the app. So each format is built once, on
an explicit "Generate" click, cached in session_state keyed to a fingerprint
of the current view; a filter change invalidates the cache and the trigger
reappears.
"""

from collections.abc import Callable
from datetime import datetime

import pandas as pd
import streamlit as st

from lib.brief import cached_brief_for
from lib.data import get_sync_state
from lib.extras import get_extras_context
from lib.facts import build_fact_pack
from lib.filters import FilterState, describe
from lib.report import build_excel_report, build_pdf_report
from lib.report_data import build_aggregate_tables, build_chart_panels


def _fingerprint(df: pd.DataFrame, filters: FilterState) -> tuple:
    return (describe(filters), filters.exclude_mega_deals, tuple(df["record_id"]))


def _render_format_button(
    state_prefix: str,
    label: str,
    extension: str,
    mime: str,
    fingerprint: tuple,
    build_fn: Callable[[datetime], bytes],
) -> None:
    bytes_key = f"__report_{state_prefix}_bytes"
    fp_key = f"__report_{state_prefix}_fingerprint"
    date_key = f"__report_{state_prefix}_date"

    if st.session_state.get(fp_key) == fingerprint and st.session_state.get(bytes_key) is not None:
        generated_at = st.session_state[date_key]
        st.download_button(
            label,
            data=st.session_state[bytes_key],
            file_name=f"biond_bd_report_{generated_at:%Y-%m-%d}.{extension}",
            mime=mime,
            icon=":material/download:",
            key=f"report_{state_prefix}_download",
        )
        return

    if st.button(f"Generate {label}", key=f"report_{state_prefix}_generate"):
        with st.spinner("Preparing report..."):
            generated_at = datetime.now()
            data = build_fn(generated_at)
        st.session_state[bytes_key] = data
        st.session_state[fp_key] = fingerprint
        st.session_state[date_key] = generated_at
        st.rerun()  # re-enter this function so the now-cached bytes render as a real download button


def render_report_download(df_filtered: pd.DataFrame, df_all: pd.DataFrame, filters: FilterState) -> None:
    with st.popover("Download report", icon=":material/download:"):
        fingerprint = _fingerprint(df_filtered, filters)
        extras = get_extras_context(df_filtered, filters)
        fact_pack = build_fact_pack(df_filtered, df_all, filters)
        brief = cached_brief_for(fact_pack, extras)
        sync_state = get_sync_state()

        _render_format_button(
            "excel", "Excel (.xlsx)", "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            fingerprint,
            lambda generated_at: build_excel_report(
                df_filtered, fact_pack, brief,
                build_aggregate_tables(df_filtered, filters), extras, filters, sync_state, generated_at,
            ),
        )
        _render_format_button(
            "pdf", "PDF", "pdf", "application/pdf",
            fingerprint,
            lambda generated_at: build_pdf_report(
                df_filtered, fact_pack, brief,
                build_chart_panels(df_filtered, filters), extras, filters, sync_state, generated_at,
            ),
        )

        if brief is None:
            st.caption(
                "AI brief not generated yet for this view -- the report will use the computed summary."
            )
