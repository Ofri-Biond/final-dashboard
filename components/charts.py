"""Pure Plotly figure factories: Aggregate -> go.Figure. No `streamlit` import --
keeps these reusable by the future PDF/report renderer and unit-testable without
a Streamlit runtime. Trace styling (bar corner radius, spline lines, donut hole,
colorway) comes from the "biond" template registered in assets/theme.py and
applies automatically to any go.Figure built after assets.theme.register() runs.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from assets.theme import SLATE, TEAL
from lib.aggregate import Aggregate, group_column

_OTHER_LABEL = "Other"


def _label(value: object) -> str:
    """Render an axis category as text. A "year" group column is float64 in the
    real data (pandas upcasts int+None to float for the undated rows) -- print
    whole numbers as "2024", never "2024.0".
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def trend_bars_and_value(
    counts: Aggregate, values: Aggregate, count_label: str, value_label: str
) -> go.Figure:
    """Deal count (bars) and disclosed value (spline+fill line) over the same year
    axis, stacked in two rows rather than sharing one axis (no dual axes).
    """
    count_col = group_column(counts)
    value_col = group_column(values)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08)
    fig.add_trace(
        go.Bar(
            x=counts.frame[count_col].map(_label), y=counts.frame["value"], name=count_label
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=values.frame[value_col].map(_label), y=values.frame["value"], name=value_label,
            mode="lines", fill="tozeroy",
        ),
        row=2, col=1,
    )
    fig.update_yaxes(title_text=count_label, row=1, col=1)
    fig.update_yaxes(title_text=value_label, row=2, col=1)
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.08), row=2, col=1)
    fig.update_layout(showlegend=False)
    return fig


def stacked_share(agg: Aggregate, x: str, color: str) -> go.Figure:
    """100%-stacked bars: `agg` is a share() result (values already percentages),
    grouped by `color` within `x`.
    """
    fig = go.Figure()
    for category in agg.frame[color].unique():
        subset = agg.frame[agg.frame[color] == category].sort_values(x)
        fig.add_trace(go.Bar(x=subset[x].map(_label), y=subset["value"], name=str(category)))
    fig.update_layout(barmode="stack", xaxis_title="Year", yaxis_title="% of deals")
    return fig


def ranked_bars(agg: Aggregate, label: str) -> go.Figure:
    """Horizontal top-N bar chart. Assumes `agg` is already narrowed (e.g. via
    lib.aggregate.top_n) -- this factory only orders and draws.
    """
    group_col = group_column(agg)
    frame = agg.frame.sort_values("value", ascending=True)  # ascending: largest ends up on top
    fig = go.Figure(go.Bar(x=frame["value"], y=frame[group_col], orientation="h"))
    fig.update_layout(xaxis_title=label, yaxis_title=None)
    return fig


def paired_ranked_bars(count_agg: Aggregate, value_agg: Aggregate) -> go.Figure:
    """Count and value side by side, sharing one category order taken from
    `count_agg`. A category with no disclosed value is left as a gap, never 0.
    """
    count_col = group_column(count_agg)
    value_col = group_column(value_agg)

    ordered = count_agg.frame.sort_values("value", ascending=True)
    categories = ordered[count_col].tolist()
    value_by_category = value_agg.frame.set_index(value_col)["value"]
    aligned_values = [value_by_category.get(c) for c in categories]

    fig = make_subplots(
        rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.05,
        subplot_titles=("Deal count", "Disclosed value ($M)"),
    )
    fig.add_trace(
        go.Bar(x=ordered["value"], y=categories, orientation="h", name="Count"), row=1, col=1
    )
    fig.add_trace(
        go.Bar(x=aligned_values, y=categories, orientation="h", name="Value"), row=1, col=2
    )
    fig.update_xaxes(title_text="Deals", row=1, col=1)
    fig.update_xaxes(title_text="Disclosed value ($M)", row=1, col=2)
    fig.update_layout(showlegend=False)
    return fig


def donut(agg: Aggregate, max_slices: int = 5) -> go.Figure:
    """Pie with a hole, tail collapsed into "Other" so it never exceeds
    `max_slices` slices regardless of how many categories the data has.
    """
    group_col = group_column(agg)
    ranked = agg.frame.sort_values("value", ascending=False)

    if len(ranked) > max_slices:
        head = ranked.iloc[: max_slices - 1]
        other_total = ranked.iloc[max_slices - 1 :]["value"].sum()
        other_row = pd.DataFrame({group_col: [_OTHER_LABEL], "value": [other_total]})
        ranked = pd.concat([head, other_row], ignore_index=True)

    return go.Figure(
        go.Pie(
            labels=ranked[group_col],
            values=ranked["value"],
            hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
        )
    )


def activity_grid(agg: Aggregate, index: str, columns: str, accent: str = TEAL) -> go.Figure:
    """Company x year (or similar) heatmap. `agg` is a count aggregate -- 0 is a
    legitimate value here (no deals that period), unlike money aggregates.

    Color encodes each cell's count as a share of the grid's busiest cell (so the
    scale stays meaningful regardless of how active the top company is), while
    `customdata`+`hovertemplate` keep the real count discoverable on hover.
    """
    pivot = agg.frame.pivot(index=index, columns=columns, values="value").fillna(0)
    peak = pivot.values.max() if pivot.values.size else 0
    peak = peak or 1
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values / peak,
            x=[_label(c) for c in pivot.columns],
            y=pivot.index,
            customdata=pivot.values,
            hovertemplate="%{y} — %{x}: %{customdata:.0f} deals<extra></extra>",
            colorscale=[[0, "#FFFFFF"], [1, accent]],
            colorbar=dict(title="Share of peak", tickformat=".0%"),
            xgap=2,
            ygap=2,
        )
    )
    fig.update_xaxes(title_text="Year")
    fig.update_yaxes(title_text="Collaborator", autorange="reversed")
    fig.update_layout(font=dict(color=SLATE))
    return fig
