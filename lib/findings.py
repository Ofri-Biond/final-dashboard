"""Plain-English finding sentences from an already-computed Aggregate. Pure
functions, no Streamlit, no re-aggregation -- callers pass the same Aggregate
they hand to a chart factory in components/charts.py.
"""

from lib.aggregate import Aggregate, group_column


def _fmt(value: float) -> str:
    return f"{value:,.0f}"


def _label(value: object) -> str:
    """Render a group key as text. A "year" group column is float64 in the real
    data (pandas upcasts int+None to float for the undated rows) -- print whole
    numbers as "2024", never "2024.0".
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def trend_finding(agg: Aggregate, noun: str) -> str:
    """`agg` grouped by a single, sortable period column (e.g. year). `noun` is the
    sentence subject, e.g. "Deal count".
    """
    frame = agg.frame
    if frame.empty:
        return f"Not enough data to describe the {noun.lower()} trend."

    group_col = group_column(agg)
    frame = frame.sort_values(group_col)
    peak = frame.loc[frame["value"].idxmax()]
    latest = frame.iloc[-1]

    if len(frame) < 2:
        return f"{noun} totals {_fmt(latest['value'])} in {_label(latest[group_col])}."

    prev = frame.iloc[-2]
    if latest["value"] > prev["value"]:
        trend = "climbing"
    elif latest["value"] < prev["value"]:
        trend = "cooling"
    else:
        trend = "flat"

    if peak[group_col] == latest[group_col]:
        return (
            f"{noun} peaked in {_label(latest[group_col])} at {_fmt(latest['value'])} "
            f"and is still {trend}."
        )
    return (
        f"{noun} peaked in {_label(peak[group_col])} ({_fmt(peak['value'])}) and is {trend} — "
        f"{_fmt(latest['value'])} in {_label(latest[group_col])}."
    )


def leader_finding(agg: Aggregate, noun: str) -> str:
    """`agg` grouped by one category (e.g. technology), unranked. `noun` is the unit
    being counted, e.g. "deals".
    """
    frame = agg.frame
    if frame.empty:
        return f"No {noun} in this selection."

    group_col = group_column(agg)
    ranked = frame.sort_values("value", ascending=False)
    top = ranked.iloc[0]

    if len(ranked) == 1:
        return f"{_label(top[group_col])} is the only entry, with {_fmt(top['value'])} {noun}."

    second = ranked.iloc[1]
    return (
        f"{_label(top[group_col])} leads with {_fmt(top['value'])} {noun}, ahead of "
        f"{_label(second[group_col])} ({_fmt(second['value'])})."
    )


def mix_finding(agg: Aggregate, within: str) -> str:
    """`agg` is a `share()` result (values are percentages) grouped by category and
    `within` (e.g. year). Describes how the largest current category has moved.
    """
    frame = agg.frame
    if frame.empty:
        return "Not enough data to describe the mix."

    group_col = group_column(agg, within)
    periods = sorted(frame[within].unique())
    last_period = periods[-1]
    last_frame = frame[frame[within] == last_period].sort_values("value", ascending=False)
    if last_frame.empty:
        return "Not enough data to describe the mix."
    leader = last_frame.iloc[0]

    if len(periods) < 2:
        return f"{_label(leader[group_col])} leads the mix at {leader['value']:.0f}%."

    first_period = periods[0]
    first_frame = frame[frame[within] == first_period]
    matching = first_frame[first_frame[group_col] == leader[group_col]]
    first_share = float(matching["value"].iloc[0]) if not matching.empty else 0.0

    if leader["value"] > first_share:
        direction = "grew"
    elif leader["value"] < first_share:
        direction = "shrank"
    else:
        direction = "held steady"

    return (
        f"{_label(leader[group_col])} {direction} from {first_share:.0f}% to "
        f"{leader['value']:.0f}% of the mix between {_label(first_period)} and "
        f"{_label(last_period)}."
    )


def concentration_finding(agg: Aggregate, noun: str, top: int = 3) -> str:
    """`agg` grouped by one category, unranked. `noun` names the group, e.g.
    "regions". Reports what share of the total the top `top` groups hold.
    """
    frame = agg.frame
    total = frame["value"].sum() if not frame.empty else 0
    if not total:
        return f"No {noun} data in this selection."

    ranked = frame.sort_values("value", ascending=False).head(top)
    share = ranked["value"].sum() / total * 100
    return f"The top {len(ranked)} {noun} account for {share:.0f}% of the total."
