import datetime
import json

import pandas as pd

from lib.aggregate import summarize
from lib.facts import build_fact_pack
from lib.filters import FilterState

# Anchor date for the trailing-12-month windows: build_fact_pack derives them
# from max(deal_date) across the whole (unfiltered) frame passed in, so every
# fixture below places its "current" deals within 12 months of ANCHOR and its
# "prior" deals in the 12 months before that.
ANCHOR = datetime.date(2026, 6, 1)
CURRENT_DATE = datetime.date(2026, 5, 1)
PRIOR_DATE = datetime.date(2025, 3, 1)


def _deal(
    year,
    deal_date,
    technologies=("B",),
    deal_type_groups=("Investment",),
    collaborators=(),
    originator=None,
    based_at="USA",
    phase="Unspecified",
    total_musd=100.0,
    upfront_musd=50.0,
    is_mega_deal=False,
) -> dict:
    return {
        "year": year,
        "deal_date": deal_date,
        "technologies": list(technologies),
        "deal_type_groups": list(deal_type_groups),
        "collaborators": list(collaborators),
        "originator": originator,
        "based_at": based_at,
        "phase": phase,
        "total_musd": total_musd,
        "upfront_musd": upfront_musd,
        "has_disclosed_total": total_musd is not None,
        "has_disclosed_upfront": upfront_musd is not None,
        "is_mega_deal": is_mega_deal,
    }


def _shifts_frame(with_mega: bool = False) -> pd.DataFrame:
    """10 current-window deals + 10 prior-window deals, engineered so every
    period-comparison detector has something to find: technology "A" quadruples
    its share, "Europe" quadruples its share, "NewCo" only appears now,
    "OldCo" only appears in the prior window, and the disclosure rate jumps.
    """
    deals = []
    for i in range(10):
        tech = "A" if i < 8 else "B"
        geo = "Europe" if i < 8 else "USA"
        collabs = ["Common"] + (["NewCo"] if i < 2 else [])
        disclosed = i < 9
        deals.append(_deal(
            2026, CURRENT_DATE, technologies=[tech], based_at=geo, collaborators=collabs,
            total_musd=100.0 if disclosed else None, upfront_musd=50.0 if disclosed else None,
        ))
    if with_mega:
        deals.append(_deal(
            2026, CURRENT_DATE, technologies=["A"], based_at="Europe", collaborators=["Common"],
            total_musd=20_000.0, upfront_musd=5_000.0, is_mega_deal=True,
        ))
    for i in range(10):
        tech = "A" if i < 2 else "B"
        geo = "Europe" if i < 2 else "USA"
        collabs = ["Common"] + (["OldCo"] if i < 3 else [])
        disclosed = i < 5
        deals.append(_deal(
            2025, PRIOR_DATE, technologies=[tech], based_at=geo, collaborators=collabs,
            total_musd=100.0 if disclosed else None, upfront_musd=50.0 if disclosed else None,
        ))
    return pd.DataFrame(deals)


def _flat_frame() -> pd.DataFrame:
    """Current and prior windows with identical shape -- no share shift, no
    new entrants/exits, no geography move, no disclosure change. Every
    detector should stay silent on this frame.
    """
    deals = []
    for date_, year in [(CURRENT_DATE, 2026), (PRIOR_DATE, 2025)]:
        for i in range(10):
            tech = "A" if i < 5 else "B"
            geo = "Europe" if i < 5 else "USA"
            deals.append(_deal(
                year, date_, technologies=[tech], based_at=geo, collaborators=["Common"],
                total_musd=100.0 if i < 8 else None, upfront_musd=50.0 if i < 8 else None,
            ))
    return pd.DataFrame(deals)


def test_kpi_current_matches_summarize_directly():
    df = _shifts_frame()
    filters = FilterState()
    pack = build_fact_pack(df, df, filters)

    assert pack["kpis"]["current"]["deal_count"] == summarize(df, "count").value
    assert pack["kpis"]["current"]["disclosed_total_value_musd"] == round(
        summarize(df, "sum", "total_musd", exclude_mega=filters.exclude_mega_deals).value, 1
    )
    assert pack["kpis"]["current"]["median_total_musd"] == round(
        summarize(df, "median", "total_musd", exclude_mega=filters.exclude_mega_deals).value, 1
    )


def test_pack_is_json_serializable_and_years_are_ints_not_floats():
    df = _shifts_frame()
    df["year"] = df["year"].astype(float)  # real data: year is float64 with NaN
    pack = build_fact_pack(df, df, FilterState())

    json.dumps(pack)  # must not raise
    for row in pack["trends"]["by_year"]:
        assert isinstance(row["year"], int)


def test_undated_deals_excluded_from_period_windows_and_counted_as_missing():
    df = _shifts_frame()
    undated = _deal(None, None, technologies=["A"], collaborators=["Ghost"])
    df = pd.concat([df, pd.DataFrame([undated])], ignore_index=True)

    pack = build_fact_pack(df, df, FilterState())

    assert pack["snapshot"]["deals_missing_date"] == 1
    assert pack["snapshot"]["deal_count"] == len(df)
    total_windowed = pack["periods"]["current"]["deal_count"] + pack["periods"]["prior"]["deal_count"]
    assert total_windowed == len(df) - 1  # the undated row is in neither window
    assert not any(
        e["name"] == "Ghost"
        for miss in pack["candidate_misses"] if miss["kind"] == "new_entrant"
        for e in miss["numbers"]["entrants"]
    )


def test_disclosure_shift_is_unaffected_by_the_mega_deal_toggle():
    df = _shifts_frame(with_mega=True)

    pack_excluded = build_fact_pack(df, df, FilterState(exclude_mega_deals=True))
    pack_included = build_fact_pack(df, df, FilterState(exclude_mega_deals=False))

    def disclosure_numbers(pack):
        return next(m["numbers"] for m in pack["candidate_misses"] if m["kind"] == "disclosure_shift")

    assert disclosure_numbers(pack_excluded) == disclosure_numbers(pack_included)


def test_no_prior_period_still_runs_period_detectors():
    # Only two years of data with no room to look further back -- previous_period
    # returns None for the KPI comparison, but the trailing-12-month detectors
    # don't depend on it and should still fire.
    df = _shifts_frame()
    pack = build_fact_pack(df, df, FilterState())

    assert pack["kpis"]["prior"] is None
    assert pack["kpis"]["prior_period_absent_reason"] is not None
    assert pack["periods"] is not None
    assert any(m["kind"] == "share_shift" for m in pack["candidate_misses"])


def test_detectors_fire_on_a_shifted_frame():
    pack = build_fact_pack(_shifts_frame(), _shifts_frame(), FilterState())
    kinds = {m["kind"] for m in pack["candidate_misses"]}

    assert "share_shift" in kinds
    assert "new_entrant" in kinds
    assert "quiet_exit" in kinds
    assert "geography_shift" in kinds
    assert "disclosure_shift" in kinds

    entrants = next(m for m in pack["candidate_misses"] if m["kind"] == "new_entrant")
    assert any(e["name"] == "NewCo" for e in entrants["numbers"]["entrants"])

    exits = next(m for m in pack["candidate_misses"] if m["kind"] == "quiet_exit")
    assert any(e["name"] == "OldCo" for e in exits["numbers"]["exits"])

    tech_shift = next(
        m for m in pack["candidate_misses"] if m["kind"] == "share_shift" and m["subject"] == "A"
    )
    assert tech_shift["numbers"]["ratio"] >= 2.0


def test_detectors_stay_silent_on_a_flat_frame():
    pack = build_fact_pack(_flat_frame(), _flat_frame(), FilterState())
    kinds = {m["kind"] for m in pack["candidate_misses"]}

    assert "share_shift" not in kinds
    assert "new_entrant" not in kinds
    assert "quiet_exit" not in kinds
    assert "geography_shift" not in kinds
    assert "disclosure_shift" not in kinds


def test_phase_shift_reports_phase_labels_across_years():
    deals = []
    for _ in range(15):
        deals.append(_deal(
            2015, datetime.date(2015, 6, 1), deal_type_groups=["License"], phase="Preclinical",
        ))
    for _ in range(15):
        deals.append(_deal(
            2020, datetime.date(2020, 6, 1), deal_type_groups=["License"], phase="Phase 2",
        ))
    df = pd.DataFrame(deals)

    pack = build_fact_pack(df, df, FilterState())
    phase_miss = next(m for m in pack["candidate_misses"] if m["kind"] == "phase_shift")

    assert phase_miss["numbers"]["first_period"]["median_phase"] == "Preclinical"
    assert phase_miss["numbers"]["last_period"]["median_phase"] == "Phase 2"
    assert phase_miss["numbers"]["first_period"]["share_at_or_before_phase1_pct"] == 100.0
    assert phase_miss["numbers"]["last_period"]["share_at_or_before_phase1_pct"] == 0.0


def test_pack_is_byte_identical_when_built_twice():
    df = _shifts_frame()
    first = build_fact_pack(df, df, FilterState())
    second = build_fact_pack(df, df, FilterState())

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
