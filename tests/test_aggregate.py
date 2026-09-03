import pandas as pd
import pytest

from lib.aggregate import aggregate, explode, monthly, share, summarize, top_n


def _deals_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_id": "a",
                "year": 2023,
                "technologies": ["ADC"],
                "collaborators": ["Pfizer"],
                "total_musd": 100.0,
                "upfront_musd": 10.0,
                "is_mega_deal": False,
            },
            {
                "record_id": "b",
                "year": 2023,
                "technologies": ["ADC"],
                "collaborators": ["Roche", "VC Fund"],  # syndicate: 2 collaborators
                "total_musd": None,  # undisclosed -- must never become 0
                "upfront_musd": None,
                "is_mega_deal": False,
            },
            {
                "record_id": "c",
                "year": 2024,
                "technologies": ["Small molecule"],
                "collaborators": ["VC Fund"],  # appears only inside a syndicate row too
                "total_musd": 20000.0,  # mega deal
                "upfront_musd": 500.0,
                "is_mega_deal": True,
            },
        ]
    )


def test_count_never_touched_by_none_values():
    df = _deals_frame()
    result = aggregate(df, by="technologies", measure="count")
    row = result.frame.set_index("technologies").loc["ADC", "value"]
    assert row == 2
    assert result.coverage.used == 3  # all 3 deals have a technology listed
    assert result.coverage.total == 3


def test_sum_drops_none_and_reports_coverage_not_zero():
    df = _deals_frame()
    result = aggregate(df, by="technologies", measure="sum", value_col="total_musd")
    frame = result.frame.set_index("technologies")
    assert frame.loc["ADC", "value"] == 100.0  # row b's None excluded, not counted as 0
    assert result.coverage.used == 2  # a and c have disclosed totals
    assert result.coverage.total == 3
    assert result.coverage.missing == 1


def test_coverage_arithmetic_holds():
    df = _deals_frame()
    result = aggregate(df, by="technologies", measure="sum", value_col="upfront_musd")
    assert result.coverage.used + result.coverage.missing == result.coverage.total


def test_collaborator_explode_credits_syndicate_members_including_solo_appearance():
    df = _deals_frame()
    result = aggregate(df, by="collaborators", measure="count")
    counts = result.frame.set_index("collaborators")["value"]
    assert counts["Pfizer"] == 1
    assert counts["Roche"] == 1
    assert counts["VC Fund"] == 2  # appears in row b's syndicate AND row c alone


def test_mega_deal_toggle_changes_value_but_not_count():
    df = _deals_frame()
    counts_with = aggregate(df, by="technologies", measure="count", exclude_mega=True)
    counts_without = aggregate(df, by="technologies", measure="count", exclude_mega=False)
    pd.testing.assert_frame_equal(counts_with.frame, counts_without.frame)

    sums_with = aggregate(
        df, by="technologies", measure="sum", value_col="total_musd", exclude_mega=True
    )
    sums_without = aggregate(
        df, by="technologies", measure="sum", value_col="total_musd", exclude_mega=False
    )
    assert "Small molecule" not in sums_with.frame["technologies"].values
    assert "Small molecule" in sums_without.frame["technologies"].values


def test_explode_drops_empty_lists():
    df = pd.DataFrame([{"technologies": ["ADC"]}, {"technologies": []}])
    result = explode(df, "technologies")
    assert len(result) == 1


def test_coverage_total_matches_used_unit_for_multi_valued_list_column():
    # A deal with two technologies must not make used > total (a negative
    # Coverage.missing) -- total has to count in the same (exploded) unit as used.
    df = pd.DataFrame(
        [
            {
                "record_id": "a",
                "technologies": ["ADC", "Multi-specific engager"],  # 2 techs, 1 deal
                "total_musd": 100.0,
                "is_mega_deal": False,
            },
            {
                "record_id": "b",
                "technologies": ["ADC"],
                "total_musd": None,
                "is_mega_deal": False,
            },
        ]
    )
    result = aggregate(df, by="technologies", measure="sum", value_col="total_musd")
    assert result.coverage.total == 3  # 3 exploded (deal, tech) pairs: a x2, b x1
    assert result.coverage.used == 2  # a's two pairs both have a disclosed value
    assert result.coverage.missing == 1  # b's one pair does not
    assert result.coverage.used <= result.coverage.total  # never negative "missing"


def test_top_n_preserves_coverage():
    df = _deals_frame()
    agg = aggregate(df, by="technologies", measure="count")
    top = top_n(agg, n=1)
    assert len(top.frame) == 1
    assert top.coverage == agg.coverage


def test_sum_requires_value_col():
    df = _deals_frame()
    with pytest.raises(ValueError):
        aggregate(df, by="technologies", measure="sum")


def test_summarize_count_ignores_none_and_mega_toggle():
    df = _deals_frame()
    result = summarize(df, measure="count")
    assert result.value == 3.0
    assert result.coverage.used == 3
    assert result.coverage.total == 3


def test_summarize_sum_drops_none_not_as_zero():
    df = _deals_frame()
    result = summarize(df, measure="sum", value_col="total_musd")
    assert result.value == 20100.0  # a (100) + c (20000); b's None excluded
    assert result.coverage.used == 2
    assert result.coverage.missing == 1


def test_summarize_mega_toggle_only_affects_money():
    df = _deals_frame()
    excluded = summarize(df, measure="sum", value_col="total_musd", exclude_mega=True)
    assert excluded.value == 100.0  # c (the mega deal) dropped
    assert excluded.coverage.used == 1

    counts_with = summarize(df, measure="count", exclude_mega=True)
    counts_without = summarize(df, measure="count", exclude_mega=False)
    assert counts_with.value == counts_without.value == 3.0


def test_summarize_returns_none_when_nothing_measurable():
    df = _deals_frame()
    only_undisclosed = df[df["record_id"] == "b"]
    result = summarize(only_undisclosed, measure="sum", value_col="total_musd")
    assert result.value is None
    assert result.coverage.used == 0


def _monthly_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"record_id": "a", "deal_date": pd.Timestamp("2024-01-15"), "total_musd": 10.0},
            {"record_id": "b", "deal_date": pd.Timestamp("2024-01-20"), "total_musd": None},
            {"record_id": "c", "deal_date": pd.Timestamp("2024-03-01"), "total_musd": 30.0},
            {"record_id": "d", "deal_date": None, "total_musd": 40.0},
        ]
    )


def test_monthly_count_buckets_by_calendar_month_sorted():
    df = _monthly_frame()
    result = monthly(df, measure="count")
    months = result.frame["month"].tolist()
    assert months == sorted(months)
    assert result.frame.set_index("month").loc["2024-01", "value"] == 2


def test_monthly_sum_drops_none_and_undated_rows():
    df = _monthly_frame()
    result = monthly(df, measure="sum", value_col="total_musd")
    # row b (undisclosed) and row d (undated) both excluded from the money series
    assert result.coverage.used == 2
    assert set(result.frame["month"]) == {"2024-01", "2024-03"}


def test_share_sums_to_100_within_group():
    df = pd.DataFrame(
        [
            {"category": "License", "year": 2023},
            {"category": "License", "year": 2023},
            {"category": "Investment", "year": 2023},
            {"category": "M&A", "year": 2024},
        ]
    )
    counts = aggregate(df, by="category", measure="count", year_col="year")
    result = share(counts, within="year")
    totals = result.frame.groupby("year")["value"].sum()
    assert totals.round(6).tolist() == [100.0, 100.0]
    license_share = result.frame.set_index("category").loc["License", "value"]
    assert license_share == pytest.approx(66.666667)
