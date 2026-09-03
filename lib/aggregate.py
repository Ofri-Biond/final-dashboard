from dataclasses import dataclass
from typing import Literal

import pandas as pd

Measure = Literal["count", "sum", "median"]

# Deal columns that hold a list of values rather than a scalar -- grouping by one of
# these must explode it first so every element (e.g. every syndicate member) is
# credited. Kept as an explicit set rather than sniffed at runtime.
_LIST_COLUMNS = {
    "indications_raw",
    "indications",
    "technologies",
    "technologies_raw",
    "deal_types",
    "deal_type_groups",
    "collaborators",
}


@dataclass(frozen=True)
class Coverage:
    used: int
    total: int
    undated: int = 0

    @property
    def missing(self) -> int:
        return self.total - self.used

    def note(self) -> str:
        text = f"Based on {self.used} of {self.total} deals"
        if self.missing:
            text += f" — {self.missing} had no disclosed value"
        if self.undated:
            text += f"; includes {self.undated} deals with no date"
        return text


@dataclass(frozen=True)
class Aggregate:
    frame: pd.DataFrame  # tidy columns: [group, (year,) value]
    coverage: Coverage


@dataclass(frozen=True)
class Scalar:
    value: float | None  # None only when measure="count" can't happen; money w/ no rows
    coverage: Coverage


def group_column(agg: Aggregate, *exclude: str) -> str:
    """The single non-"value" column in `agg.frame`, excluding any named in
    `exclude` (e.g. a "within" grouping column). Lets callers key off the group
    without hard-coding a column name or order.
    """
    return next(c for c in agg.frame.columns if c not in ("value", *exclude))


def explode(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """One row per element of a list column; rows with an empty list are dropped."""
    return df.explode(column).dropna(subset=[column])


def _measurable(df: pd.DataFrame, value_col: str | None, exclude_mega: bool) -> pd.DataFrame:
    """Rows a money measure may use: mega-deals dropped if asked, then undisclosed
    (None value_col) rows dropped -- never imputed as 0. No-op for value_col=None.
    """
    if value_col is None:
        return df
    working = df[~df["is_mega_deal"]] if exclude_mega else df
    return working.dropna(subset=[value_col])


def aggregate(
    df: pd.DataFrame,
    by: str,
    measure: Measure = "count",
    value_col: str | None = None,
    year_col: str | None = None,
    exclude_mega: bool = False,
) -> Aggregate:
    """Group `df` by `by` (and optionally `year_col`), computing `measure`.

    `by` may name a list column (e.g. "technologies") -- it is exploded first, so a
    syndicate row credits every member. Money measures ("sum"/"median") drop rows
    with a None value_col and report that in Coverage; they never treat None as 0.
    The mega-deal toggle only ever affects money measures, never "count" (US2).
    """
    working = explode(df, by) if by in _LIST_COLUMNS else df
    # total must be counted in the same unit as `used` below (post-explode) --
    # otherwise a multi-valued list column (e.g. two technologies on one deal)
    # makes used > total and Coverage.missing go negative.
    total = len(working)

    undated = int(df["year"].isna().sum()) if "year" in df.columns else 0
    group_cols = [by] + ([year_col] if year_col else [])

    if measure == "count":
        used = len(working)
        grouped = working.groupby(group_cols).size().reset_index(name="value")
        return Aggregate(frame=grouped, coverage=Coverage(used=used, total=total, undated=undated))

    if value_col is None:
        raise ValueError(f"measure={measure!r} requires value_col")

    money = _measurable(working, value_col, exclude_mega)
    used = len(money)

    agg_func = "sum" if measure == "sum" else "median"
    grouped = money.groupby(group_cols)[value_col].agg(agg_func).reset_index(name="value")
    return Aggregate(frame=grouped, coverage=Coverage(used=used, total=total, undated=undated))


def summarize(
    df: pd.DataFrame,
    measure: Measure = "count",
    value_col: str | None = None,
    exclude_mega: bool = False,
) -> Scalar:
    """Like `aggregate` with no grouping -- one number for the whole frame. Powers
    KPI cards. An empty measurable slice yields value=None, never 0.
    """
    total = len(df)
    undated = int(df["year"].isna().sum()) if "year" in df.columns else 0

    if measure == "count":
        coverage = Coverage(used=total, total=total, undated=undated)
        return Scalar(value=float(total), coverage=coverage)

    if value_col is None:
        raise ValueError(f"measure={measure!r} requires value_col")

    money = _measurable(df, value_col, exclude_mega)
    used = len(money)
    coverage = Coverage(used=used, total=total, undated=undated)
    if used == 0:
        return Scalar(value=None, coverage=coverage)

    value = money[value_col].sum() if measure == "sum" else money[value_col].median()
    return Scalar(value=float(value), coverage=coverage)


def monthly(
    df: pd.DataFrame,
    measure: Measure = "count",
    value_col: str | None = None,
    exclude_mega: bool = False,
) -> Aggregate:
    """Aggregate by calendar month of `deal_date`, sorted chronologically. Powers
    st.metric sparklines. Rows with no deal_date are excluded (they can't place on
    a month axis) -- their count still shows up in Coverage.undated.
    """
    total = len(df)
    undated = int(df["year"].isna().sum()) if "year" in df.columns else 0
    dated = df.dropna(subset=["deal_date"]).copy()
    dated["month"] = pd.to_datetime(dated["deal_date"]).dt.to_period("M").astype(str)

    if measure == "count":
        used = len(dated)
        grouped = dated.groupby("month").size().reset_index(name="value").sort_values("month")
        return Aggregate(frame=grouped, coverage=Coverage(used=used, total=total, undated=undated))

    if value_col is None:
        raise ValueError(f"measure={measure!r} requires value_col")

    money = _measurable(dated, value_col, exclude_mega)
    used = len(money)
    agg_func = "sum" if measure == "sum" else "median"
    grouped = (
        money.groupby("month")[value_col].agg(agg_func).reset_index(name="value").sort_values("month")
    )
    return Aggregate(frame=grouped, coverage=Coverage(used=used, total=total, undated=undated))


def share(agg: Aggregate, within: str) -> Aggregate:
    """Turn `value` into a percentage within each `within` group (e.g. year) --
    each group's shares sum to 100. Coverage carried over unchanged, as in top_n.
    """
    frame = agg.frame.copy()
    totals = frame.groupby(within)["value"].transform("sum")
    frame["value"] = (frame["value"] / totals * 100).where(totals > 0, 0.0)
    return Aggregate(frame=frame, coverage=agg.coverage)


def top_n(agg: Aggregate, n: int) -> Aggregate:
    """Top n rows by value, coverage carried over unchanged (it describes the whole group)."""
    frame = agg.frame.sort_values("value", ascending=False).head(n).reset_index(drop=True)
    return Aggregate(frame=frame, coverage=agg.coverage)
