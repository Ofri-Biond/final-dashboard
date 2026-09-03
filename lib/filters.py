from collections.abc import Mapping
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
# years/quarters allow null passthrough: undated rows (year/quarter is None) always
# pass those filters -- they are never silently dropped by narrowing a selection.
_FILTER_COLUMNS = [
    ("years", "year", False, True, int),
    ("quarters", "quarter", False, True, int),
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
    "quarters": "Quarter",
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
    quarters: tuple[int, ...] = field(default_factory=tuple)
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


def previous_period(filters: FilterState, data_years: tuple[int, int]) -> FilterState | None:
    """A same-length year window immediately preceding filters.years, for KPI deltas.
    Falls back to the data's own range when no year filter is set. None when the
    data doesn't extend far enough back to fill even a partial prior window.
    """
    start, end = (min(filters.years), max(filters.years)) if filters.years else data_years
    length = end - start + 1
    prev_end = start - 1
    if prev_end < data_years[0]:
        return None
    prev_start = max(prev_end - length + 1, data_years[0])
    return replace(filters, years=tuple(range(prev_start, prev_end + 1)))


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
