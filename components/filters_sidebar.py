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

import functools
import logging
from collections.abc import Callable

import pandas as pd
import streamlit as st

from assets import theme
from components.states import clear_filters, safe_render
from lib.data import (
    clear_deals_cache,
    dictionary_categories,
    get_sync_state,
    load_extras,
    sync_extras_now,
    sync_now,
)
from lib.filters import FilterState, apply_filters, sync_periods_to_years
from lib.models import PHASE_ORDER

logger = logging.getLogger(__name__)


def _safe_options(build: Callable[..., list]) -> Callable[..., list]:
    """A filter whose options can't be built (missing column, unsortable values)
    is offered empty instead of failing the whole sidebar."""
    @functools.wraps(build)
    def wrapper(*args, **kwargs) -> list:
        try:
            return build(*args, **kwargs)
        except Exception:
            logger.exception("Could not build filter options in %s", build.__name__)
            return []
    return wrapper


@_safe_options
def _unique_options(df: pd.DataFrame, column: str) -> list:
    return sorted(df[column].dropna().unique())


@_safe_options
def _year_options(df: pd.DataFrame) -> list[int]:
    return sorted(int(y) for y in df["year"].dropna().unique())


@_safe_options
def _list_options(df: pd.DataFrame, column: str) -> list[str]:
    return sorted(df[column].explode().dropna().unique().tolist())


@_safe_options
def _category_options(df: pd.DataFrame, column: str, dictionary: str) -> list[str]:
    """Only real main categories from the dictionary YAML -- an unmapped raw value
    passes through normalize() under its own label, but it's a sub-category, not a
    category, so it's offered in the sub-category filter only."""
    categories = dictionary_categories(dictionary)
    return [value for value in _list_options(df, column) if value in categories]


@_safe_options
def _phase_options(df: pd.DataFrame) -> list[str]:
    present = set(df["phase"].dropna().unique())
    return [phase for phase in PHASE_ORDER if phase in present]


@_safe_options
def _period_options(df: pd.DataFrame, years: list[int]) -> list[str]:
    """Quarters ("2026-Q1") present in the data, newest first, limited to the selected
    years when any. Already-selected periods stay offered so narrowing the years
    never invalidates a live selection."""
    in_scope = df if not years else df[df["year"].isin(years)]
    options = set(in_scope["period"].dropna().unique())
    options.update(st.session_state.get("periods", []))
    return sorted(options, reverse=True)


def _on_years_change(available_periods: list[str]) -> None:
    st.session_state["periods"] = list(sync_periods_to_years(
        st.session_state.get("years", []), st.session_state.get("periods", []), available_periods,
    ))


def render_sidebar(df: pd.DataFrame) -> FilterState:
    year_options = _year_options(df)

    with st.sidebar:
        st.header(":material/filter_alt: Filters")

        years = st.multiselect(
            "Year", options=year_options, key="years", bind="query-params",
            on_change=_on_years_change, args=(_unique_options(df, "period"),),
        )
        periods = st.multiselect(
            "Quarter", options=_period_options(df, years), key="periods", bind="query-params",
            help="Pick specific quarters of specific years -- e.g. 2026-Q1 and 2025-Q3.",
        )
        if years or periods:
            st.caption(":material/info: Deals with no date are left out while a year or quarter is selected.")
        technologies = st.multiselect(
            "Technology category", options=_category_options(df, "technologies", "technology"),
            key="technologies", bind="query-params",
        )
        technologies_raw = st.multiselect(
            "Technology sub-category", options=_list_options(df, "technologies_raw"),
            key="technologies_raw", bind="query-params",
        )
        deal_types = st.multiselect(
            "Deal type category", options=_category_options(df, "deal_type_groups", "deal_type"),
            key="deal_types", bind="query-params",
        )
        deal_types_raw = st.multiselect(
            "Deal type sub-category", options=_list_options(df, "deal_types"),
            key="deal_types_raw", bind="query-params",
        )

        # Phase/geography/indication options narrow to what's still reachable once
        # year + quarter + technology + deal type (category or sub-category) are picked (dependent options).
        try:
            scoped = apply_filters(
                df,
                FilterState(
                    years=tuple(years), periods=tuple(periods),
                    technologies=tuple(technologies), technologies_raw=tuple(technologies_raw),
                    deal_types=tuple(deal_types), deal_types_raw=tuple(deal_types_raw),
                ),
            )
        except Exception:
            logger.exception("Could not narrow the dependent filter options")
            scoped = df  # offer every option rather than none
        geographies = st.multiselect(
            "Geography", options=_unique_options(scoped, "based_at"),
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
            periods=tuple(periods),
            technologies=tuple(technologies),
            technologies_raw=tuple(technologies_raw),
            deal_types=tuple(deal_types),
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
        safe_render("Data freshness", _render_freshness)

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
            sync_extras_now()
        clear_deals_cache()
        load_extras.clear()
        st.rerun()
