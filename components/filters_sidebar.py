"""Sidebar: filters only, bound to URL query params, then data freshness +
refresh below a divider. Renders a FilterState from the widget values -- it
does not touch FilterState.from_query/to_query, which Streamlit's own
bind="query-params" makes redundant here (they remain the serialization used
by reports/deep-links elsewhere).

Technology/Deal type/Indication filter on the raw Airtable values, not the
dictionary groups, so the sidebar offers exactly what the source data says.
The canonical groups are still what the charts aggregate by -- notably the
Who-is-active deal-type split, which reads deal_type_groups directly.
"""

import pandas as pd
import streamlit as st

from assets import theme
from components.states import clear_filters
from lib.data import get_sync_state, load_deals, sync_now
from lib.filters import FilterState, apply_filters
from lib.models import PHASE_ORDER


def _list_options(df: pd.DataFrame, column: str) -> list[str]:
    return sorted(df[column].explode().dropna().unique().tolist())


def _phase_options(df: pd.DataFrame) -> list[str]:
    present = set(df["phase"].dropna().unique())
    return [phase for phase in PHASE_ORDER if phase in present]


def render_sidebar(df: pd.DataFrame) -> FilterState:
    year_options = sorted(int(y) for y in df["year"].dropna().unique())

    with st.sidebar:
        st.header(":material/filter_alt: Filters")

        years = st.multiselect(
            "Year", options=year_options, key="years", bind="query-params",
        )
        quarters = st.multiselect(
            "Quarter", options=[1, 2, 3, 4], format_func=lambda q: f"Q{q}",
            key="quarters", bind="query-params",
        )
        technologies_raw = st.multiselect(
            "Technology", options=_list_options(df, "technologies_raw"),
            key="technologies_raw", bind="query-params",
        )
        deal_types_raw = st.multiselect(
            "Deal type", options=_list_options(df, "deal_types"),
            key="deal_types_raw", bind="query-params",
        )

        # Phase/geography/indication options narrow to what's still reachable once
        # year + quarter + technology + deal type are picked (dependent options).
        scoped = apply_filters(
            df,
            FilterState(
                years=tuple(years), quarters=tuple(quarters),
                technologies_raw=tuple(technologies_raw), deal_types_raw=tuple(deal_types_raw),
            ),
        )
        geographies = st.multiselect(
            "Geography", options=sorted(scoped["based_at"].dropna().unique()),
            key="geographies", bind="query-params",
        )
        phases = st.multiselect(
            "Phase", options=_phase_options(scoped), key="phases", bind="query-params",
        )
        indications_raw = st.multiselect(
            "Indication", options=_list_options(scoped, "indications_raw"),
            key="indications_raw", bind="query-params",
        )
        exclude_mega = st.toggle(
            "Exclude mega-deals (≥ $10,000M)", value=True,
            key="exclude_mega_deals", bind="query-params",
        )

        filters = FilterState(
            years=tuple(years),
            quarters=tuple(quarters),
            technologies_raw=tuple(technologies_raw),
            deal_types_raw=tuple(deal_types_raw),
            geographies=tuple(geographies),
            phases=tuple(phases),
            indications_raw=tuple(indications_raw),
            exclude_mega_deals=exclude_mega,
        )

        if filters.active_count and st.button(f"Clear filters ({filters.active_count})"):
            clear_filters()

        st.divider()
        st.selectbox(
            "Chart colors", options=list(theme.PALETTES),
            key="chart_palette", bind="query-params",
            help="Switch to a colorblind-safe palette for all charts.",
        )
        st.divider()
        _render_freshness()

    return filters


def _render_freshness() -> None:
    sync_state = get_sync_state()
    if sync_state is None:
        st.warning("No data cached yet.")
    elif sync_state.status == "failed":
        st.warning(f"Last sync failed: {sync_state.error_message}. Showing last good data.")
    else:
        st.caption(f"Data as of {sync_state.last_sync_at:%H:%M}")

    if st.button("Refresh"):
        with st.spinner("Syncing..."):
            sync_now()
        load_deals.clear()
        st.rerun()
