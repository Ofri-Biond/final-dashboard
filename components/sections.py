"""The three chart sections and the raw-data expander. Each chart is the same
unit: a finding sentence (with an Excel export alongside it), the figure, and
(money charts only) a coverage caption. Chart/finding/coverage construction
lives in lib.report_data, shared with the downloadable report (lib/report.py)
so the two can never disagree about a chart's data.
"""

import pandas as pd
import streamlit as st

from components import states
from lib.filters import FilterState, apply_filters
from lib.report_data import (
    ChartPanel,
    build_landscape_panels,
    build_players_panels,
    build_trending_panels,
)


def _render_panel(panel: ChartPanel) -> None:
    text_col, export_col = st.columns([0.85, 0.15])
    with text_col:
        states.finding(panel.finding)
    with export_col:
        states.download_button(panel.export_sheets, panel.export_filename, panel.key)
    states.plot(panel.figure, key=panel.key)


def _render_trending_section(df: pd.DataFrame, filters: FilterState) -> None:
    st.subheader(":material/trending_up: How is the market trending?")
    st.caption("Deal volume and disclosed value by year, and how the deal-type mix has shifted.")
    left, right = st.columns([3, 2])

    trend_panel, mix_panel = build_trending_panels(df, filters)
    with left:
        _render_panel(trend_panel)
        states.coverage_caption(trend_panel.coverage)
    with right:
        _render_panel(mix_panel)


def _render_landscape_section(df: pd.DataFrame, filters: FilterState) -> None:
    st.subheader(":material/explore: Where & what?")
    st.caption("Therapeutic areas, technologies, and where deals are happening.")
    area_col, tech_col, geo_col = st.columns(3)

    areas_panel, tech_panel, geo_panel = build_landscape_panels(df, filters)
    with area_col:
        _render_panel(areas_panel)
    with tech_col:
        _render_panel(tech_panel)
        states.coverage_caption(tech_panel.coverage)
    with geo_col:
        _render_panel(geo_panel)


def _render_players_subsection(df: pd.DataFrame, label: str, key_prefix: str) -> None:
    left, right = st.columns([2, 3])
    top_panel, grid_panel = build_players_panels(df, label, key_prefix)

    with left:
        _render_panel(top_panel)
    with right:
        _render_panel(grid_panel)
        st.caption(
            "Color shows each cell's deal count as a share of the busiest cell shown here "
            "(count ÷ peak count); hover a cell for the exact number of deals."
        )


def _render_players_section(df: pd.DataFrame) -> None:
    st.subheader(":material/groups: Who is active?")
    st.caption("Most active collaborators, and who has shown up or gone quiet year to year.")
    st.caption("IPO and Other deal types aren't shown in either tab below.")

    investing, dealmaking = st.tabs(["Investments", "M&A / Licensing"])
    with investing:
        investors = apply_filters(df, FilterState(deal_types=("Investment",)))
        _render_players_subsection(investors, "investors", "invest")
    with dealmaking:
        dealmakers = apply_filters(df, FilterState(deal_types=("M&A", "License")))
        _render_players_subsection(dealmakers, "dealmakers", "deal")


def render_sections(df: pd.DataFrame, filters: FilterState) -> None:
    _render_trending_section(df, filters)
    _render_landscape_section(df, filters)
    _render_players_section(df)


def render_raw_data(df: pd.DataFrame) -> None:
    with st.expander("Raw data preview", icon=":material/table_view:"):
        st.dataframe(states.display_frame(df), width="stretch")
