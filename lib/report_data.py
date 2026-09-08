"""Chart-panel construction shared by the live dashboard (components/sections.py)
and the downloadable report (lib/report.py): the same lib.aggregate/lib.findings/
components.charts calls, computed once so the two renderers can never disagree
about a chart's data. Pure -- no `streamlit` import.
"""

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go

from assets import theme
from components import charts
from lib.aggregate import Aggregate, Coverage, aggregate, share, top_n
from lib.filters import FilterState, apply_filters
from lib.findings import (
    concentration_finding,
    leader_finding,
    mix_finding,
    trend_finding,
)

_TOP_N = 10
_TOP_COMPANIES_IN_GRID = 15


@dataclass(frozen=True)
class ChartPanel:
    key: str
    title: str
    finding: str
    figure: go.Figure
    coverage: Coverage | None  # None for count-only charts -- always fully covered
    export_sheets: dict[str, pd.DataFrame]
    export_filename: str


def _trend_panel(df: pd.DataFrame, filters: FilterState) -> ChartPanel:
    counts = aggregate(df, by="year", measure="count")
    values = aggregate(
        df, by="year", measure="sum", value_col="total_musd",
        exclude_mega=filters.exclude_mega_deals,
    )
    return ChartPanel(
        key="trend",
        title="Deal volume & value by year",
        finding=trend_finding(counts, "Deal count"),
        figure=charts.trend_bars_and_value(counts, values, "Deals", "Disclosed value ($M)"),
        coverage=values.coverage,
        export_sheets={"Deal count": counts.frame, "Disclosed value ($M)": values.frame},
        export_filename="deal_trend",
    )


def _mix_panel(df: pd.DataFrame, filters: FilterState) -> ChartPanel:
    by_type_year = aggregate(df, by="deal_type_groups", measure="count", year_col="year")
    mix = share(by_type_year, within="year")
    return ChartPanel(
        key="mix",
        title="Deal-type mix by year",
        finding=mix_finding(mix, within="year"),
        figure=charts.stacked_share(mix, x="year", color="deal_type_groups"),
        coverage=None,
        export_sheets={"Deal type mix": mix.frame},
        export_filename="deal_type_mix",
    )


def _areas_panel(df: pd.DataFrame) -> ChartPanel:
    areas = top_n(aggregate(df, by="indications", measure="count"), n=_TOP_N)
    return ChartPanel(
        key="areas",
        title="Top indications",
        finding=leader_finding(areas, "deals"),
        figure=charts.ranked_bars(areas, "Deals"),
        coverage=None,
        export_sheets={"Top indications": areas.frame},
        export_filename="top_indications",
    )


def _tech_panel(df: pd.DataFrame, filters: FilterState) -> ChartPanel:
    tech_counts = top_n(aggregate(df, by="technologies", measure="count"), n=_TOP_N)
    tech_values = aggregate(
        df, by="technologies", measure="sum", value_col="total_musd",
        exclude_mega=filters.exclude_mega_deals,
    )
    return ChartPanel(
        key="tech",
        title="Technology: count vs value",
        finding=leader_finding(tech_counts, "deals"),
        figure=charts.paired_ranked_bars(tech_counts, tech_values),
        coverage=tech_values.coverage,
        export_sheets={"Deal count": tech_counts.frame, "Disclosed value ($M)": tech_values.frame},
        export_filename="technology_deals",
    )


def _geo_panel(df: pd.DataFrame) -> ChartPanel:
    geography = aggregate(df, by="based_at", measure="count")
    return ChartPanel(
        key="geo",
        title="Deals by geography",
        finding=concentration_finding(geography, "regions"),
        figure=charts.donut(geography),
        coverage=None,
        export_sheets={"Deals by geography": geography.frame},
        export_filename="deals_by_geography",
    )


def _players_top_panel(df: pd.DataFrame, label: str, key_prefix: str, title: str) -> ChartPanel:
    totals = aggregate(df, by="collaborators", measure="count")
    players = top_n(totals, n=_TOP_N)
    return ChartPanel(
        key=f"{key_prefix}_players",
        title=title,
        finding=leader_finding(players, "deals"),
        figure=charts.ranked_bars(players, "Deals"),
        coverage=None,
        export_sheets={f"Top {label}": players.frame},
        export_filename=f"top_{key_prefix}",
    )


def _players_grid_panel(df: pd.DataFrame, label: str, key_prefix: str, title: str) -> ChartPanel:
    totals = aggregate(df, by="collaborators", measure="count")
    by_year = aggregate(df, by="collaborators", measure="count", year_col="year")
    top_companies = set(top_n(totals, n=_TOP_COMPANIES_IN_GRID).frame["collaborators"])
    grid = Aggregate(
        frame=by_year.frame[by_year.frame["collaborators"].isin(top_companies)],
        coverage=by_year.coverage,
    )
    return ChartPanel(
        key=f"{key_prefix}_grid",
        title=title,
        finding=concentration_finding(totals, "players"),
        figure=charts.activity_grid(
            grid, index="collaborators", columns="year", accent=theme.primary_color(),
        ),
        coverage=None,
        export_sheets={f"{label} activity by year": grid.frame},
        export_filename=f"{key_prefix}_activity",
    )


def build_trending_panels(df: pd.DataFrame, filters: FilterState) -> tuple[ChartPanel, ChartPanel]:
    return _trend_panel(df, filters), _mix_panel(df, filters)


def build_landscape_panels(
    df: pd.DataFrame, filters: FilterState
) -> tuple[ChartPanel, ChartPanel, ChartPanel]:
    return _areas_panel(df), _tech_panel(df, filters), _geo_panel(df)


def build_players_panels(df: pd.DataFrame, label: str, key_prefix: str) -> tuple[ChartPanel, ChartPanel]:
    top_title = f"Top {label}"
    grid_title = f"{label.capitalize()} activity by year"
    return (
        _players_top_panel(df, label, key_prefix, top_title),
        _players_grid_panel(df, label, key_prefix, grid_title),
    )


def build_chart_panels(df: pd.DataFrame, filters: FilterState) -> list[ChartPanel]:
    """Every chart panel shown on the dashboard, in display order -- the report's
    single source for "each current chart".
    """
    panels = list(build_trending_panels(df, filters))
    panels += build_landscape_panels(df, filters)

    investors = apply_filters(df, FilterState(deal_types=("Investment",)))
    panels += build_players_panels(investors, "investors", "invest")

    dealmakers = apply_filters(df, FilterState(deal_types=("M&A", "License")))
    panels += build_players_panels(dealmakers, "dealmakers", "deal")

    return panels


def build_aggregate_tables(df: pd.DataFrame, filters: FilterState) -> dict[str, pd.DataFrame]:
    """"By year" and "By technology" tables behind the trend/technology charts,
    each carrying its money aggregate's overall Coverage as three extra columns
    (used/total/missing) -- Coverage describes the whole aggregate, not a single
    row, so the same three numbers repeat down the column (matching the one
    coverage caption the UI shows per chart, not a per-row figure).
    """

    def _table(by: str, group_label: str) -> pd.DataFrame:
        counts = aggregate(df, by=by, measure="count")
        values = aggregate(
            df, by=by, measure="sum", value_col="total_musd",
            exclude_mega=filters.exclude_mega_deals,
        )
        merged = pd.merge(
            counts.frame.rename(columns={"value": "Deal count"}),
            values.frame.rename(columns={"value": "Disclosed value ($M)"}),
            on=by, how="outer",
        )
        merged["Deal count"] = merged["Deal count"].fillna(0).astype(int)
        merged = merged.rename(columns={by: group_label})
        merged["Value coverage used"] = values.coverage.used
        merged["Value coverage total"] = values.coverage.total
        merged["Value coverage missing"] = values.coverage.missing
        return merged.sort_values(group_label).reset_index(drop=True)

    by_year = _table("year", "Year")
    by_year["Year"] = by_year["Year"].apply(lambda v: int(v) if pd.notna(v) else v)
    by_technology = _table("technologies", "Technology").sort_values(
        "Deal count", ascending=False
    ).reset_index(drop=True)

    return {"By year": by_year, "By technology": by_technology}
