import pandas as pd

from lib.aggregate import Aggregate, Coverage
from lib.findings import concentration_finding, leader_finding, mix_finding, trend_finding


def _agg(frame: pd.DataFrame) -> Aggregate:
    return Aggregate(frame=frame, coverage=Coverage(used=len(frame), total=len(frame)))


def test_trend_finding_names_peak_year_and_cooling_direction():
    frame = pd.DataFrame({"year": [2022, 2023, 2024], "value": [50, 155, 90]})
    result = trend_finding(_agg(frame), "Deal count")
    assert "2023" in result
    assert "155" in result
    assert "cooling" in result


def test_trend_finding_still_climbing_when_latest_is_the_peak():
    frame = pd.DataFrame({"year": [2022, 2023, 2024], "value": [50, 90, 155]})
    result = trend_finding(_agg(frame), "Deal count")
    assert "still climbing" in result


def test_trend_finding_neutral_on_empty_frame():
    frame = pd.DataFrame({"year": [], "value": []})
    result = trend_finding(_agg(frame), "Deal count")
    assert "Not enough data" in result


def test_leader_finding_names_top_two():
    frame = pd.DataFrame(
        {"technologies": ["Small molecule", "ADC", "CAR"], "value": [136, 92, 40]}
    )
    result = leader_finding(_agg(frame), "deals")
    assert "Small molecule leads with 136 deals" in result
    assert "ADC" in result


def test_leader_finding_single_entry():
    frame = pd.DataFrame({"technologies": ["ADC"], "value": [92]})
    result = leader_finding(_agg(frame), "deals")
    assert "only entry" in result


def test_leader_finding_neutral_on_empty_frame():
    frame = pd.DataFrame({"technologies": [], "value": []})
    result = leader_finding(_agg(frame), "deals")
    assert "No deals" in result


def test_mix_finding_reports_growth_of_the_current_leader():
    frame = pd.DataFrame(
        {
            "deal_type_groups": ["License", "Investment", "License", "Investment"],
            "year": [2023, 2023, 2024, 2024],
            "value": [60.0, 40.0, 70.0, 30.0],
        }
    )
    result = mix_finding(_agg(frame), within="year")
    assert "License" in result
    assert "grew" in result
    assert "60%" in result
    assert "70%" in result


def test_mix_finding_single_period_reports_current_leader_only():
    frame = pd.DataFrame(
        {"deal_type_groups": ["License", "Investment"], "year": [2024, 2024], "value": [60.0, 40.0]}
    )
    result = mix_finding(_agg(frame), within="year")
    assert "leads the mix" in result


def test_mix_finding_neutral_on_empty_frame():
    frame = pd.DataFrame({"deal_type_groups": [], "year": [], "value": []})
    result = mix_finding(_agg(frame), within="year")
    assert "Not enough data" in result


def test_concentration_finding_computes_share_of_the_true_total():
    frame = pd.DataFrame(
        {"based_at": ["USA", "Europe", "China", "Asia"], "value": [375, 98, 96, 14]}
    )
    result = concentration_finding(_agg(frame), "regions", top=3)
    share = round((375 + 98 + 96) / (375 + 98 + 96 + 14) * 100)
    assert "top 3 regions" in result
    assert f"{share}%" in result


def test_concentration_finding_neutral_when_nothing_to_measure():
    frame = pd.DataFrame({"based_at": [], "value": []})
    result = concentration_finding(_agg(frame), "regions")
    assert "No regions data" in result
