import pandas as pd

from components import charts
from lib.aggregate import Aggregate, Coverage


def _agg(frame: pd.DataFrame) -> Aggregate:
    return Aggregate(frame=frame, coverage=Coverage(used=len(frame), total=len(frame)))


def test_donut_collapses_tail_into_other_beyond_max_slices():
    frame = pd.DataFrame(
        {
            "based_at": ["USA", "Europe", "China", "Asia", "Canada", "Israel"],
            "value": [10, 8, 6, 4, 2, 1],
        }
    )
    fig = charts.donut(_agg(frame), max_slices=5)
    labels = list(fig.data[0].labels)
    assert len(labels) == 5
    assert "Other" in labels


def test_donut_keeps_all_slices_when_within_max():
    frame = pd.DataFrame({"based_at": ["USA", "Europe"], "value": [10, 8]})
    fig = charts.donut(_agg(frame), max_slices=5)
    assert len(fig.data[0].labels) == 2


def test_trend_bars_and_value_uses_two_stacked_axes_not_a_dual_axis():
    counts = _agg(pd.DataFrame({"year": [2023, 2024], "value": [10, 20]}))
    values = _agg(pd.DataFrame({"year": [2023, 2024], "value": [100.0, 200.0]}))
    fig = charts.trend_bars_and_value(counts, values, "Deals", "Value ($M)")

    yaxis_keys = [k for k in fig.layout if k.startswith("yaxis")]
    assert len(yaxis_keys) == 2
    # a dual axis sets `overlaying` to plot a second axis over the first; two
    # stacked subplots instead never do
    for key in yaxis_keys:
        assert getattr(fig.layout[key], "overlaying", None) is None


def test_trend_bars_and_value_puts_bars_above_the_value_line():
    counts = _agg(pd.DataFrame({"year": [2023], "value": [10]}))
    values = _agg(pd.DataFrame({"year": [2023], "value": [100.0]}))
    fig = charts.trend_bars_and_value(counts, values, "Deals", "Value ($M)")
    assert [trace.type for trace in fig.data] == ["bar", "scatter"]


def test_ranked_bars_orders_largest_value_on_top():
    frame = pd.DataFrame({"technologies": ["Small molecule", "ADC"], "value": [10, 20]})
    fig = charts.ranked_bars(_agg(frame), "Deals")
    assert fig.data[0].y[-1] == "ADC"  # last in a horizontal bar's y-list renders at the top


def test_paired_ranked_bars_leaves_a_gap_not_zero_for_missing_value():
    counts = _agg(pd.DataFrame({"technologies": ["ADC", "CAR"], "value": [10, 5]}))
    values = _agg(pd.DataFrame({"technologies": ["ADC"], "value": [100.0]}))  # CAR undisclosed
    fig = charts.paired_ranked_bars(counts, values)
    value_trace = fig.data[1]
    car_index = list(value_trace.y).index("CAR")
    assert value_trace.x[car_index] is None


def test_activity_grid_pivots_to_a_company_by_year_matrix():
    frame = pd.DataFrame(
        {
            "collaborators": ["Pfizer", "Pfizer", "Roche"],
            "year": [2023, 2024, 2023],
            "value": [2, 1, 3],
        }
    )
    fig = charts.activity_grid(_agg(frame), index="collaborators", columns="year")
    heatmap = fig.data[0]
    assert set(heatmap.x) == {"2023", "2024"}
    assert set(heatmap.y) == {"Pfizer", "Roche"}


def test_activity_grid_normalizes_color_but_keeps_raw_counts_for_hover():
    frame = pd.DataFrame(
        {
            "collaborators": ["Pfizer", "Pfizer", "Roche"],
            "year": [2023, 2024, 2023],
            "value": [2, 1, 3],
        }
    )
    fig = charts.activity_grid(_agg(frame), index="collaborators", columns="year")
    heatmap = fig.data[0]
    assert heatmap.z.max() == 1.0  # normalized to the busiest cell (Roche/2023's 3 deals)
    assert heatmap.z.min() >= 0.0
    assert set(heatmap.customdata.flatten()) == {0.0, 1.0, 2.0, 3.0}


def test_activity_grid_handles_an_empty_segment_without_raising():
    frame = pd.DataFrame({"collaborators": [], "year": [], "value": []})
    fig = charts.activity_grid(_agg(frame), index="collaborators", columns="year")
    assert list(fig.data[0].x) == []
