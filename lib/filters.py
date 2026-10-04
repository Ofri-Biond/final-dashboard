from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

import pandas as pd

# Every filter field: (state field, deal column it filters, is that column a list?,
# does an unknown/null value on that column always pass this filter?, the type its
# values parse to). The single source of truth for from_query/to_query/active_count/
# apply_filters/most_restrictive below, so adding a filter is a one-line change to
# this table alone.
# A "_raw" field filters the dictionary-unmapped value (e.g. "Option to license")
# independently of its mapped group (e.g. "License") -- both may be set at once and
# combine with AND, like any other pair of filters.
# years/periods allow null passthrough: undated rows (year/period is None) always
# pass those filters. A period is a specific quarter of a specific year ("2026-Q1"),
# so periods from different years mix freely -- unlike independent year + quarter lists.
# Undated rows are never silently dropped by narrowing a selection.
_FILTER_COLUMNS = [
    ("years", "year", False, True, int),
    ("periods", "period", False, True, str),
    ("indications", "indications", True, False, str),
    ("indications_raw", "indications_raw", True, False, str),
    ("technologies", "technologies", True, False, str),
    ("technologies_raw", "technologies_raw", True, False, str),
    ("deal_types", "deal_type_groups", True, False, str),
    ("deal_types_raw", "deal_types", True, False, str),
    ("geographies", "based_at", False, False, str),
    ("phases", "phase", False, False, str),
]
_MULTISELECT_FIELDS = [state_field for state_field, *_ in _FILTER_COLUMNS]

# Human labels for most_restrictive()'s empty-state message. Kept next to
# _FILTER_COLUMNS since it enumerates the same fields.
_FIELD_LABELS: dict[str, str] = {
    "years": "Year",
    "periods": "Quarter",
    "indications": "Indication",
    "indications_raw": "Indication (raw)",
    "technologies": "Technology",
    "technologies_raw": "Technology (raw)",
    "deal_types": "Deal type",
    "deal_types_raw": "Deal type (raw)",
    "geographies": "Geography",
    "phases": "Phase",
}


@dataclass(frozen=True)
class FilterState:
    years: tuple[int, ...] = field(default_factory=tuple)
    periods: tuple[str, ...] = field(default_factory=tuple)
    indications: tuple[str, ...] = field(default_factory=tuple)
    indications_raw: tuple[str, ...] = field(default_factory=tuple)
    technologies: tuple[str, ...] = field(default_factory=tuple)
    technologies_raw: tuple[str, ...] = field(default_factory=tuple)
    deal_types: tuple[str, ...] = field(default_factory=tuple)
    deal_types_raw: tuple[str, ...] = field(default_factory=tuple)
    geographies: tuple[str, ...] = field(default_factory=tuple)
    phases: tuple[str, ...] = field(default_factory=tuple)
    exclude_mega_deals: bool = True

    @classmethod
    def from_query(cls, params: Mapping[str, str]) -> "FilterState":
        kwargs = {
            state_field: _parse_list(params.get(state_field), value_type)
            for state_field, _, _, _, value_type in _FILTER_COLUMNS
        }
        return cls(
            exclude_mega_deals=_parse_bool(params.get("exclude_mega_deals"), default=True),
            **kwargs,
        )

    def to_query(self) -> dict[str, str]:
        query: dict[str, str] = {}
        for name in _MULTISELECT_FIELDS:
            values = getattr(self, name)
            if values:
                query[name] = ",".join(str(v) for v in values)
        if not self.exclude_mega_deals:
            query["exclude_mega_deals"] = "0"
        return query

    @property
    def active_count(self) -> int:
        count = 0
        if self.exclude_mega_deals != FilterState().exclude_mega_deals:
            count += 1
        count += sum(1 for name in _MULTISELECT_FIELDS if getattr(self, name))
        return count


def _parse_list(raw: str | None, value_type: type = str) -> tuple:
    if not raw:
        return ()
    values = [v for v in raw.split(",") if v]
    if value_type is int:
        try:
            return tuple(int(v) for v in values)
        except ValueError:
            return ()
    return tuple(values)


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw != "0"


def apply_filters(df: pd.DataFrame, filters: FilterState) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)

    for state_field, column, is_list_column, allow_null, _value_type in _FILTER_COLUMNS:
        selected = getattr(filters, state_field)
        if not selected:
            continue
        selected_set = set(selected)
        if is_list_column:
            col_mask = df[column].apply(
                lambda values, wanted=selected_set: bool(wanted.intersection(values))
            )
        else:
            col_mask = df[column].isin(selected_set)
        if allow_null:
            col_mask = col_mask | df[column].isna()
        mask &= col_mask

    return df[mask]


def data_year_range(df: pd.DataFrame) -> tuple[int, int]:
    """(first, last) year present in the data; (0, 0) when no deal has a date, which
    previous_period reads as "no earlier period exists"."""
    years = df["year"].dropna()
    return (int(years.min()), int(years.max())) if not years.empty else (0, 0)


def selected_years(filters: FilterState) -> tuple[int, ...]:
    """The years the selection covers: filters.years, else the years of filters.periods.
    Empty when no time filter is set."""
    if filters.years:
        return tuple(sorted(filters.years))
    return tuple(sorted({int(p[:4]) for p in filters.periods}))


def sync_periods_to_years(
    years: Iterable[int], periods: Iterable[str], available_periods: Iterable[str]
) -> tuple[str, ...]:
    """The Quarter selection after the Year selection changes: quarters of removed
    years are dropped, and a newly selected year (one with no quarter picked) gets
    all of its quarters, so adding a year never silently contributes nothing. An
    empty Quarter selection already means "every quarter" and is left alone.
    """
    years, periods = set(years), tuple(periods)
    if not years or not periods:
        return periods
    kept = [p for p in periods if int(p[:4]) in years]
    covered = {int(p[:4]) for p in kept}
    added = [p for p in available_periods if int(p[:4]) in years - covered]
    return tuple(sorted(set(kept) | set(added), reverse=True))


def _same_quarter_last_year(period: str) -> str:
    return f"{int(period[:4]) - 1}{period[4:]}"


def previous_period(filters: FilterState, data_years: tuple[int, int]) -> FilterState | None:
    """The period immediately preceding the selection, for KPI deltas. With specific
    quarters selected it is the same quarters one year earlier (2026-Q1 -> 2025-Q1);
    otherwise a same-length year window before filters.years (the data's own range
    when no year filter is set). None when the data doesn't reach back far enough.
    """
    if filters.periods:
        shifted = tuple(
            _same_quarter_last_year(p) for p in filters.periods
            if int(p[:4]) - 1 >= data_years[0]
        )
        return replace(filters, years=(), periods=shifted) if shifted else None

    start, end = (min(filters.years), max(filters.years)) if filters.years else data_years
    length = end - start + 1
    prev_end = start - 1
    if prev_end < data_years[0]:
        return None
    prev_start = max(prev_end - length + 1, data_years[0])
    return replace(filters, years=tuple(range(prev_start, prev_end + 1)))


_DESCRIBE_MAX_VALUES = 4


def describe(filters: FilterState) -> str:
    """A one-line human summary of the active filters, e.g. "Technology: CAR T
    cells; Year: 2020, 2024" -- for the AI brief footer, so it can say exactly
    what view a cached brief was generated for. Values are sorted (years/labels
    alike) so the same filter selection always describes the same way,
    regardless of the order widgets were touched in.
    """
    parts = []
    for state_field in _MULTISELECT_FIELDS:
        values = getattr(filters, state_field)
        if not values:
            continue
        shown = sorted(values, key=str)
        text = ", ".join(str(v) for v in shown[:_DESCRIBE_MAX_VALUES])
        if len(shown) > _DESCRIBE_MAX_VALUES:
            text += f" (+{len(shown) - _DESCRIBE_MAX_VALUES} more)"
        parts.append(f"{_FIELD_LABELS[state_field]}: {text}")

    if not filters.exclude_mega_deals:
        parts.append("Mega-deals included")

    return "; ".join(parts) if parts else "No filters (all deals)"


def most_restrictive(df: pd.DataFrame, filters: FilterState, n: int = 2) -> list[str]:
    """Labels of the `n` active filters that, applied alone, remove the most rows --
    the two "culprit filters" named in the empty-state message.
    """
    total = len(df)
    removals: list[tuple[str, int]] = []

    for state_field in _MULTISELECT_FIELDS:
        value = getattr(filters, state_field)
        if not value:
            continue
        solo = replace(FilterState(), **{state_field: value})
        removed = total - len(apply_filters(df, solo))
        removals.append((_FIELD_LABELS[state_field], removed))

    removals.sort(key=lambda pair: pair[1], reverse=True)
    return [label for label, _ in removals[:n]]
