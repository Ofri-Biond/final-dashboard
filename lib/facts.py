"""The fact pack: every number the AI Market Brief is allowed to talk about,
precomputed in pure Python. No Streamlit, no `anthropic` import here -- this
module only produces a JSON-serializable dict (build_fact_pack) and its plain-
English fallback rendering (snapshot_lines).

Two different "prior period" concepts are used, and both are labelled in the
pack so they can't be confused:

- `kpis` mirrors components/kpis.py exactly (same summarize() calls, same
  previous_period() window) so the brief's headline numbers can never disagree
  with the KPI cards rendered above it.
- `periods`/`candidate_misses` compare two trailing-12-month windows anchored
  on the latest deal_date in the whole dataset, not on the year filter. This is
  deliberate: previous_period() returns None on the unfiltered view (the data
  spans 2010-2026, so there's no year before 2010 to compare against), and the
  year filter lets undated deals through on both sides of any comparison
  (lib/filters.py's allow_null=True), which would silently damp every delta.
  Trailing-date windows exist on every view and never include undated rows.
"""

from dataclasses import replace
from datetime import timedelta

import pandas as pd

from lib.aggregate import aggregate, explode, summarize, top_n
from lib.filters import FilterState, apply_filters, describe, previous_period
from lib.models import PHASE_ORDER

FACT_PACK_VERSION = 1

_TOP_N = 5
_MIN_SHARE_SHIFT_DEALS = 5
_MIN_LICENSE_DEALS_PER_YEAR = 15
_MIN_NEW_ENTRANT_DEALS = 2
_MIN_QUIET_EXIT_DEALS = 3
_MIN_GEOGRAPHY_DEALS = 5
_GEOGRAPHY_SHIFT_PP = 5.0
_DISCLOSURE_SHIFT_PP = 10.0
_ZERO_UPFRONT_SHARE_TRIGGER = 0.05

# PHASE_ORDER is a closed enum ending in "Unspecified" (lib/models.py), which
# isn't a point on the development-stage axis -- exclude it from the ordinal.
_PHASE_ORDINALS = {p: i for i, p in enumerate(PHASE_ORDER) if p != "Unspecified"}
_ORDINAL_TO_PHASE = {i: p for p, i in _PHASE_ORDINALS.items()}
_PHASE_1_ORDINAL = _PHASE_ORDINALS["Phase 1"]


def _jsonify(value):
    """Recursively coerce a value into something json.dumps can serialize
    losslessly and deterministically: numpy/pandas scalars -> Python scalars,
    NaN/NaT -> None, date/Timestamp -> ISO string, floats rounded to 1dp so the
    same underlying number always renders (and hashes) the same way. Does NOT
    reorder lists -- callers that build a list from a set (new entrants, quiet
    exits, ...) are responsible for sorting it themselves with an explicit key,
    since some lists (top-5 rankings, per-year trends) have meaningful order
    that a generic re-sort would destroy.
    """
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonify(v) for v in value]
    if value is None:
        return None
    if hasattr(value, "item"):  # numpy scalar (int64, float64, bool_, ...) -> python scalar
        return _jsonify(value.item())
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return None if pd.isna(value) else round(value, 1)
    if isinstance(value, int):
        return value
    if hasattr(value, "isoformat"):  # date, datetime, Timestamp, NaT
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return value.isoformat()
    return value


def _ranked(counts: pd.Series, min_count: int, top: int) -> list[tuple[str, int]]:
    """(name, count) pairs with count >= min_count, sorted count desc then name
    asc -- deterministic regardless of the set/groupby iteration order that
    produced `counts` (which, under hash randomization, can vary run to run).
    """
    items = [(str(name), int(count)) for name, count in counts.items() if count >= min_count]
    items.sort(key=lambda pair: (-pair[1], pair[0]))
    return items[:top]


def _rate(numerator: int, denominator: int) -> float | None:
    return (numerator / denominator) if denominator else None


# ---------------------------------------------------------------------------
# KPIs -- mirrors components/kpis.py exactly.
# ---------------------------------------------------------------------------

_KPI_FIELDS = [
    ("deal_count", "count", None),
    ("disclosed_total_value_musd", "sum", "total_musd"),
    ("median_total_musd", "median", "total_musd"),
    ("median_upfront_musd", "median", "upfront_musd"),
]


def _kpi_values(df: pd.DataFrame, filters: FilterState) -> dict:
    return {
        key: summarize(df, measure, value_col, exclude_mega=filters.exclude_mega_deals).value
        for key, measure, value_col in _KPI_FIELDS
    }


def _kpis(
    df: pd.DataFrame, df_all: pd.DataFrame, filters: FilterState, data_year_range: tuple[int, int]
) -> dict:
    current = _kpi_values(df, filters)
    prev_filters = previous_period(filters, data_year_range)

    if prev_filters is None:
        return {
            "current": current,
            "prior": None,
            "prior_period_years": None,
            "prior_period_absent_reason": (
                "no prior period available before the earliest year in the data "
                f"({data_year_range[0]})"
            ),
        }

    prev_years = (
        [min(prev_filters.years), max(prev_filters.years)]
        if prev_filters.years
        else list(data_year_range)
    )
    prev_df = apply_filters(df_all, prev_filters)
    return {
        "current": current,
        "prior": _kpi_values(prev_df, filters),
        "prior_period_years": prev_years,
        "prior_period_absent_reason": None,
    }


# ---------------------------------------------------------------------------
# Trailing-12-month windows for the detectors and the trend/YoY sections.
# ---------------------------------------------------------------------------


def _date_windows(df_all: pd.DataFrame, filters: FilterState):
    """Two trailing-12-month windows (current, prior) anchored on the latest
    deal_date across the WHOLE dataset (not the filtered view, so the anchor
    doesn't move when a year filter narrows the view), each further scoped by
    every active filter except years/quarters. Also returns `historical` --
    everything dated before the current window, under the same non-year scope
    -- which quiet-exit detection needs (a wider "has this ever happened"
    baseline, not just the one prior 12-month window).
    """
    non_year = replace(filters, years=(), quarters=())
    scoped = apply_filters(df_all, non_year)
    dated = scoped.dropna(subset=["deal_date"]).copy()
    dated["deal_date"] = pd.to_datetime(dated["deal_date"])

    all_dated = df_all.dropna(subset=["deal_date"])
    if all_dated.empty:
        return None

    anchor = pd.to_datetime(all_dated["deal_date"]).max()
    current_start = anchor - timedelta(days=365)
    prior_end = current_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=365)

    current_df = dated[(dated["deal_date"] > current_start) & (dated["deal_date"] <= anchor)]
    prior_df = dated[(dated["deal_date"] > prior_start) & (dated["deal_date"] <= prior_end)]
    historical_df = dated[dated["deal_date"] <= current_start]

    windows = {
        "current": {
            "start": (current_start + timedelta(days=1)).date().isoformat(),
            "end": anchor.date().isoformat(),
            "deal_count": len(current_df),
        },
        "prior": {
            "start": (prior_start + timedelta(days=1)).date().isoformat(),
            "end": prior_end.date().isoformat(),
            "deal_count": len(prior_df),
        },
    }
    return windows, current_df, prior_df, historical_df


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------


def _by_year(df: pd.DataFrame, filters: FilterState) -> list[dict]:
    counts = aggregate(df, by="year", measure="count")
    values = aggregate(
        df, by="year", measure="sum", value_col="total_musd",
        exclude_mega=filters.exclude_mega_deals,
    )
    counts_map = {row["year"]: row["value"] for _, row in counts.frame.iterrows()}
    values_map = {row["year"]: row["value"] for _, row in values.frame.iterrows()}
    return [
        {
            "year": int(year),
            "deal_count": int(counts_map[year]),
            "disclosed_value_musd": values_map.get(year),
        }
        for year in sorted(counts_map)
    ]


def _top_technologies_by_count(current_df: pd.DataFrame, prior_df: pd.DataFrame) -> dict:
    cur = top_n(aggregate(current_df, by="technologies", measure="count"), _TOP_N)
    pri = aggregate(prior_df, by="technologies", measure="count")
    pri_map = {row["technologies"]: row["value"] for _, row in pri.frame.iterrows()}
    rows = []
    for _, row in cur.frame.iterrows():
        name, cur_n = row["technologies"], int(row["value"])
        pri_n = pri_map.get(name)
        change_pct = round((cur_n - pri_n) / pri_n * 100, 1) if pri_n else None
        rows.append({
            "name": name, "deal_count": cur_n,
            "prior_period_deal_count": int(pri_n) if pri_n is not None else 0,
            "change_pct": change_pct,
        })
    return {
        "unit": "deal-technology pairs",
        "note": "each deal is credited to every technology it lists; these do not sum to the view total",
        "rows": rows,
    }


def _top_technologies_by_value(
    current_df: pd.DataFrame, prior_df: pd.DataFrame, filters: FilterState
) -> dict:
    cur = top_n(
        aggregate(
            current_df, by="technologies", measure="sum", value_col="total_musd",
            exclude_mega=filters.exclude_mega_deals,
        ),
        _TOP_N,
    )
    pri = aggregate(
        prior_df, by="technologies", measure="sum", value_col="total_musd",
        exclude_mega=filters.exclude_mega_deals,
    )
    pri_map = {row["technologies"]: row["value"] for _, row in pri.frame.iterrows()}
    rows = []
    for _, row in cur.frame.iterrows():
        name, cur_v = row["technologies"], float(row["value"])
        pri_v = pri_map.get(name)
        change_pct = round((cur_v - pri_v) / pri_v * 100, 1) if pri_v else None
        rows.append({
            "name": name, "disclosed_value_musd": cur_v,
            "prior_period_value_musd": float(pri_v) if pri_v is not None else 0.0,
            "change_pct": change_pct,
        })
    return {
        "unit": "deal-technology pairs",
        "note": "each deal is credited to every technology it lists; these do not sum to the view total",
        "rows": rows,
    }


def _top_collaborators(current_df: pd.DataFrame, prior_df: pd.DataFrame) -> dict:
    cur = top_n(aggregate(current_df, by="collaborators", measure="count"), _TOP_N)
    pri = aggregate(prior_df, by="collaborators", measure="count")
    pri_map = {row["collaborators"]: row["value"] for _, row in pri.frame.iterrows()}
    rows = []
    for _, row in cur.frame.iterrows():
        name, cur_n = row["collaborators"], int(row["value"])
        pri_n = pri_map.get(name)
        change_pct = round((cur_n - pri_n) / pri_n * 100, 1) if pri_n else None
        rows.append({
            "name": name, "deal_count": cur_n,
            "prior_period_deal_count": int(pri_n) if pri_n is not None else 0,
            "change_pct": change_pct,
        })
    return {
        "unit": "deal-company pairs",
        "note": "a syndicate deal credits every collaborator listed; these do not sum to the view total",
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Analyst-miss detectors
# ---------------------------------------------------------------------------


def _share_shift(current_df: pd.DataFrame, prior_df: pd.DataFrame, column: str, label: str) -> list[dict]:
    cur_exploded = explode(current_df, column)
    pri_exploded = explode(prior_df, column)
    cur_total, pri_total = len(cur_exploded), len(pri_exploded)
    if cur_total == 0 or pri_total == 0:
        return []

    cur_counts = cur_exploded[column].value_counts()
    pri_counts = pri_exploded[column].value_counts()

    misses = []
    for value, cur_n in cur_counts.items():
        cur_n = int(cur_n)
        if cur_n < _MIN_SHARE_SHIFT_DEALS:
            continue
        pri_n = int(pri_counts.get(value, 0))
        pri_share = pri_n / pri_total
        if pri_share <= 0:
            continue
        cur_share = cur_n / cur_total
        ratio = cur_share / pri_share
        if ratio >= 2.0 or ratio <= 0.5:
            misses.append({
                "kind": "share_shift",
                "dimension": label,
                "subject": str(value),
                "numbers": {
                    "current_deal_count": cur_n,
                    "current_share_pct": round(cur_share * 100, 1),
                    "prior_share_pct": round(pri_share * 100, 1),
                    "ratio": round(ratio, 2),
                },
            })

    misses.sort(key=lambda m: (-max(m["numbers"]["ratio"], 1 / m["numbers"]["ratio"]), m["subject"]))
    return misses


def _phase_shift(df_filtered: pd.DataFrame) -> dict | None:
    if df_filtered.empty:
        # An empty boolean mask built from .apply() on a 0-row Series comes back
        # object-dtype, not bool -- df_filtered[mask] then reads as "select these
        # (zero) column labels" rather than "keep these (zero) rows", collapsing
        # license_deals to zero columns and breaking the "phase" lookup below.
        return None
    license_deals = df_filtered[
        df_filtered["deal_type_groups"].apply(lambda groups: "License" in groups)
    ]
    valid = license_deals[license_deals["phase"].isin(_PHASE_ORDINALS)].dropna(subset=["year"])
    if valid.empty:
        return None

    counts_by_year = valid.groupby("year").size()
    eligible_years = sorted(
        year for year, n in counts_by_year.items() if n >= _MIN_LICENSE_DEALS_PER_YEAR
    )
    if len(eligible_years) < 2:
        return None

    first_year, last_year = eligible_years[0], eligible_years[-1]

    def stats(year: float) -> dict:
        sub = valid[valid["year"] == year]
        ordinals = sub["phase"].map(_PHASE_ORDINALS)
        median_ordinal = float(ordinals.median())
        nearest_label = _ORDINAL_TO_PHASE[round(median_ordinal)]
        share_early = float((ordinals <= _PHASE_1_ORDINAL).mean())
        return {
            "year": int(year),
            "deal_count": len(sub),
            "median_phase": nearest_label,
            "share_at_or_before_phase1_pct": round(share_early * 100, 1),
        }

    first, last = stats(first_year), stats(last_year)
    first_ordinal = _PHASE_ORDINALS[first["median_phase"]]
    last_ordinal = _PHASE_ORDINALS[last["median_phase"]]
    if abs(last_ordinal - first_ordinal) < 1:
        return None

    return {
        "kind": "phase_shift",
        "dimension": "phase",
        "subject": "License deals",
        "numbers": {"first_period": first, "last_period": last},
    }


def _new_entrants(current_df: pd.DataFrame, prior_df: pd.DataFrame) -> dict | None:
    current_counts = explode(current_df, "collaborators")["collaborators"].value_counts()
    prior_names = set(explode(prior_df, "collaborators")["collaborators"])
    candidates = current_counts[~current_counts.index.isin(prior_names)]
    ranked = _ranked(candidates, _MIN_NEW_ENTRANT_DEALS, _TOP_N)
    if not ranked:
        return None
    return {
        "kind": "new_entrant",
        "dimension": "collaborators",
        "subject": None,
        "numbers": {"entrants": [{"name": n, "deal_count": c} for n, c in ranked]},
    }


def _quiet_exits(current_df: pd.DataFrame, historical_df: pd.DataFrame) -> dict | None:
    historical_counts = explode(historical_df, "collaborators")["collaborators"].value_counts()
    current_names = set(explode(current_df, "collaborators")["collaborators"])
    candidates = historical_counts[~historical_counts.index.isin(current_names)]
    ranked = _ranked(candidates, _MIN_QUIET_EXIT_DEALS, _TOP_N)
    if not ranked:
        return None
    return {
        "kind": "quiet_exit",
        "dimension": "collaborators",
        "subject": None,
        "numbers": {"exits": [{"name": n, "historical_deal_count": c} for n, c in ranked]},
    }


def _geography_shift(current_df: pd.DataFrame, prior_df: pd.DataFrame) -> dict | None:
    cur_total, pri_total = len(current_df), len(prior_df)
    if cur_total == 0 or pri_total == 0:
        return None

    cur_counts = current_df["based_at"].value_counts()
    pri_counts = prior_df["based_at"].value_counts()

    movers = []
    for geo in set(cur_counts.index) | set(pri_counts.index):
        if geo == "Unknown":  # normalize.py buckets missing geography here -- not a real shift
            continue
        cur_n = int(cur_counts.get(geo, 0))
        if cur_n < _MIN_GEOGRAPHY_DEALS:
            continue
        cur_share = cur_n / cur_total
        pri_share = int(pri_counts.get(geo, 0)) / pri_total
        delta_pp = (cur_share - pri_share) * 100
        if abs(delta_pp) >= _GEOGRAPHY_SHIFT_PP:
            movers.append({
                "geography": str(geo),
                "current_deal_count": cur_n,
                "current_share_pct": round(cur_share * 100, 1),
                "prior_share_pct": round(pri_share * 100, 1),
                "change_pp": round(delta_pp, 1),
            })

    if not movers:
        return None
    movers.sort(key=lambda m: (-abs(m["change_pp"]), m["geography"]))
    return {
        "kind": "geography_shift", "dimension": "based_at", "subject": None,
        "numbers": {"movers": movers[:_TOP_N]},
    }


def _disclosure_shift(current_df: pd.DataFrame, prior_df: pd.DataFrame) -> dict | None:
    def rates(df: pd.DataFrame) -> dict | None:
        n = len(df)
        if n == 0:
            return None
        disclosed_upfront_n = int(df["has_disclosed_upfront"].sum())
        zero_upfront_n = int((df["upfront_musd"] == 0).sum())
        return {
            "deal_count": n,
            "total_disclosed_rate_pct": round(float(df["has_disclosed_total"].mean()) * 100, 1),
            "upfront_disclosed_rate_pct": round(float(df["has_disclosed_upfront"].mean()) * 100, 1),
            "zero_upfront_count": zero_upfront_n,
            "zero_upfront_share_of_disclosed_upfront_pct": round(
                _rate(zero_upfront_n, disclosed_upfront_n) * 100, 1
            ) if disclosed_upfront_n else 0.0,
        }

    current, prior = rates(current_df), rates(prior_df)
    if current is None or prior is None:
        return None

    total_delta = current["total_disclosed_rate_pct"] - prior["total_disclosed_rate_pct"]
    upfront_delta = current["upfront_disclosed_rate_pct"] - prior["upfront_disclosed_rate_pct"]
    zero_share_high = current["zero_upfront_share_of_disclosed_upfront_pct"] >= (
        _ZERO_UPFRONT_SHARE_TRIGGER * 100
    )
    if abs(total_delta) < _DISCLOSURE_SHIFT_PP and abs(upfront_delta) < _DISCLOSURE_SHIFT_PP and not zero_share_high:
        return None

    return {
        "kind": "disclosure_shift", "dimension": "disclosure", "subject": None,
        "numbers": {
            "current": current, "prior": prior,
            "total_disclosed_rate_change_pp": round(total_delta, 1),
            "upfront_disclosed_rate_change_pp": round(upfront_delta, 1),
        },
    }


def _candidate_misses(
    df_filtered: pd.DataFrame,
    current_df: pd.DataFrame,
    prior_df: pd.DataFrame,
    historical_df: pd.DataFrame,
) -> list[dict]:
    misses: list[dict] = []
    misses += _share_shift(current_df, prior_df, "technologies", "technology")
    misses += _share_shift(current_df, prior_df, "deal_type_groups", "deal_type")

    for detector in (
        lambda: _phase_shift(df_filtered),
        lambda: _new_entrants(current_df, prior_df),
        lambda: _quiet_exits(current_df, historical_df),
        lambda: _geography_shift(current_df, prior_df),
        lambda: _disclosure_shift(current_df, prior_df),
    ):
        result = detector()
        if result is not None:
            misses.append(result)

    return misses


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def _snapshot(df: pd.DataFrame, filters: FilterState) -> dict:
    total = len(df)
    dated = int(df["year"].notna().sum())
    return {
        "deal_count": total,
        "dated_deal_count": dated,
        "disclosed_total_value_musd": summarize(
            df, "sum", "total_musd", exclude_mega=filters.exclude_mega_deals
        ).value,
        "median_total_musd": summarize(
            df, "median", "total_musd", exclude_mega=filters.exclude_mega_deals
        ).value,
        "median_upfront_musd": summarize(
            df, "median", "upfront_musd", exclude_mega=filters.exclude_mega_deals
        ).value,
        "deals_with_disclosed_total": int(df["has_disclosed_total"].sum()),
        "deals_missing_total": int((~df["has_disclosed_total"]).sum()),
        "deals_with_disclosed_upfront": int(df["has_disclosed_upfront"].sum()),
        "deals_missing_upfront": int((~df["has_disclosed_upfront"]).sum()),
        "deals_with_zero_upfront": int((df["upfront_musd"] == 0).sum()),
        "deals_missing_date": int(total - dated),
    }


def _caveats(pack_snapshot: dict, filters: FilterState, windows_available: bool) -> list[str]:
    caveats = []
    if pack_snapshot["deals_missing_date"]:
        caveats.append(
            f"{pack_snapshot['deals_missing_date']} of {pack_snapshot['deal_count']} deals in "
            "this view have no date and are excluded from year trends and all period comparisons."
        )
    if pack_snapshot["deals_missing_total"]:
        caveats.append(
            f"{pack_snapshot['deals_missing_total']} deals have no disclosed total value; "
            "money figures are based only on the deals that disclosed one, never treated as zero."
        )
    if filters.exclude_mega_deals:
        caveats.append("Mega-deals (≥ $10,000M total) are excluded from money figures by the active filter.")
    if not windows_available:
        caveats.append("No dated deals are available to compute period-over-period comparisons.")
    return caveats


def build_fact_pack(
    df_filtered: pd.DataFrame,
    df_all: pd.DataFrame,
    filters: FilterState,
) -> dict:
    """The complete, JSON-serializable fact pack for the current filtered view.
    Every number the AI Market Brief may cite lives here -- lib.brief validates
    every figure in the model's output against exactly this structure.
    """
    data_year_range = (int(df_all["year"].min()), int(df_all["year"].max()))

    windows_result = _date_windows(df_all, filters)
    if windows_result is None:
        periods = None
        candidate_misses: list[dict] = []
    else:
        windows, current_df, prior_df, historical_df = windows_result
        periods = windows
        candidate_misses = _candidate_misses(df_filtered, current_df, prior_df, historical_df)

    snapshot = _snapshot(df_filtered, filters)

    trends = {"by_year": _by_year(df_filtered, filters)}
    if windows_result is not None:
        trends["top_technologies_by_count"] = _top_technologies_by_count(current_df, prior_df)
        trends["top_technologies_by_value"] = _top_technologies_by_value(current_df, prior_df, filters)
        trends["top_collaborators"] = _top_collaborators(current_df, prior_df)

    pack = {
        "version": FACT_PACK_VERSION,
        "view": {
            "filters": describe(filters),
            "exclude_mega_deals": filters.exclude_mega_deals,
            "mega_deal_threshold_musd": 10_000,
            "data_year_range": list(data_year_range),
        },
        "kpis": _kpis(df_filtered, df_all, filters, data_year_range),
        "periods": periods,
        "snapshot": snapshot,
        "trends": trends,
        "candidate_misses": candidate_misses,
        "caveats": _caveats(snapshot, filters, windows_result is not None),
    }
    return _jsonify(pack)


def snapshot_lines(fact_pack: dict) -> list[str]:
    """Plain-English rendering of the snapshot, for the AI-unavailable fallback
    -- matches the formatting components/kpis.py and components/states.py
    already use ("$1,234M" / "not disclosed").
    """
    snapshot = fact_pack["snapshot"]

    def money(value):
        return "not disclosed" if value is None else f"${value:,.0f}M"

    lines = [
        (
            f"{snapshot['deal_count']:,} deals in view "
            f"({snapshot['dated_deal_count']:,} dated, {snapshot['deals_missing_date']:,} without a date)."
        ),
        f"Disclosed total value: {money(snapshot['disclosed_total_value_musd'])}.",
        f"Median deal size: {money(snapshot['median_total_musd'])}.",
        f"Median upfront: {money(snapshot['median_upfront_musd'])}.",
        (
            f"{snapshot['deals_with_disclosed_total']:,} of {snapshot['deal_count']:,} deals disclosed "
            f"a total value; {snapshot['deals_with_disclosed_upfront']:,} disclosed an upfront "
            f"({snapshot['deals_with_zero_upfront']:,} of those disclosed as $0M)."
        ),
    ]
    lines.extend(fact_pack["caveats"])
    return lines
