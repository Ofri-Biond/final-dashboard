"""The three chart sections and the raw-data expander. Each chart is the same
unit: a finding sentence, the figure, and (money charts only) a coverage
caption. No aggregation happens here -- every number comes from lib.aggregate.
"""

import pandas as pd
import streamlit as st

from components import charts, states
from lib.aggregate import Aggregate, aggregate, share, top_n
from lib.filters import FilterState
from lib.findings import concentration_finding, leader_finding, mix_finding, trend_finding

_TOP_N = 10
_TOP_COMPANIES_IN_GRID = 15


def _render_trending_section(df: pd.DataFrame, filters: FilterState) -> None:
    st.subheader(":material/trending_up: How is the market trending?")
    st.caption("Deal volume and disclosed value by year, and how the deal-type mix has shifted.")
    left, right = st.columns([3, 2])

    with left:
        counts = aggregate(df, by="year", measure="count")
        values = aggregate(
            df, by="year", measure="sum", value_col="total_musd",
            exclude_mega=filters.exclude_mega_deals,
        )
        states.finding(trend_finding(counts, "Deal count"))
        states.plot(
            charts.trend_bars_and_value(counts, values, "Deals", "Disclosed value ($M)"),
            key="trend",
        )
        states.coverage_caption(values.coverage)

    with right:
        by_type_year = aggregate(df, by="deal_type_groups", measure="count", year_col="year")
        mix = share(by_type_year, within="year")
        states.finding(mix_finding(mix, within="year"))
        states.plot(charts.stacked_share(mix, x="year", color="deal_type_groups"), key="mix")


def _render_landscape_section(df: pd.DataFrame, filters: FilterState) -> None:
    st.subheader(":material/explore: Where & what?")
    st.caption("Therapeutic areas, technologies, and where deals are happening.")
    area_col, tech_col, geo_col = st.columns(3)

    with area_col:
        areas = top_n(aggregate(df, by="indications", measure="count"), n=_TOP_N)
        states.finding(leader_finding(areas, "deals"))
        states.plot(charts.ranked_bars(areas, "Deals"), key="areas")

    with tech_col:
        tech_counts = top_n(aggregate(df, by="technologies", measure="count"), n=_TOP_N)
        tech_values = aggregate(
            df, by="technologies", measure="sum", value_col="total_musd",
            exclude_mega=filters.exclude_mega_deals,
        )
        states.finding(leader_finding(tech_counts, "deals"))
        states.plot(charts.paired_ranked_bars(tech_counts, tech_values), key="tech")
        states.coverage_caption(tech_values.coverage)

    with geo_col:
        geography = aggregate(df, by="based_at", measure="count")
        states.finding(concentration_finding(geography, "regions"))
        states.plot(charts.donut(geography), key="geo")


def _render_players_section(df: pd.DataFrame) -> None:
    st.subheader(":material/groups: Who is active?")
    st.caption("Most active collaborators, and who has shown up or gone quiet year to year.")
    left, right = st.columns([2, 3])
    totals = aggregate(df, by="collaborators", measure="count")

    with left:
        players = top_n(totals, n=_TOP_N)
        states.finding(leader_finding(players, "deals"))
        states.plot(charts.ranked_bars(players, "Deals"), key="players")

    with right:
        by_year = aggregate(df, by="collaborators", measure="count", year_col="year")
        top_companies = set(top_n(totals, n=_TOP_COMPANIES_IN_GRID).frame["collaborators"])
        grid = Aggregate(
            frame=by_year.frame[by_year.frame["collaborators"].isin(top_companies)],
            coverage=by_year.coverage,
        )
        states.finding(concentration_finding(totals, "players"))
        states.plot(charts.activity_grid(grid, index="collaborators", columns="year"), key="grid")


def render_sections(df: pd.DataFrame, filters: FilterState) -> None:
    _render_trending_section(df, filters)
    _render_landscape_section(df, filters)
    _render_players_section(df)


def render_raw_data(df: pd.DataFrame) -> None:
    with st.expander("Raw data preview", icon=":material/table_view:"):
        st.dataframe(states.display_frame(df), width="stretch")
