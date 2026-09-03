import numpy as np

from lib.normalize import normalize
from tests.conftest import make_raw_row, raw_frame


def test_absent_keys_default_safely(dicts):
    # A row missing keys entirely, as Airtable's API omits empty fields.
    row = {"record_id": "rec1"}
    df = normalize(raw_frame(row), dicts)
    deal = df.iloc[0]
    assert deal["originator"] is None
    assert deal["collaborators"] == []
    assert deal["technologies"] == []
    assert deal["upfront_musd"] is None
    assert deal["total_musd"] is None
    assert not deal["needs_review"]
    assert not deal["auto_loaded"]
    assert deal["year"] is None
    assert deal["deal_date"] is None


def test_technology_dedupe_into_one_group(dicts):
    row = make_raw_row(
        Technology=np.array(["Bispecific antibody", "Cell engager - T cell"], dtype=object)
    )
    df = normalize(raw_frame(row), dicts)
    assert df.iloc[0]["technologies"] == ["Multi-specific engager"]


def test_unmapped_technology_passes_through_and_is_logged(dicts):
    row = make_raw_row(Technology=np.array(["Some Novel Modality"], dtype=object))
    df = normalize(raw_frame(row), dicts)
    assert df.iloc[0]["technologies"] == ["Some Novel Modality"]
    assert dicts["technology"].unmapped["Some Novel Modality"] == 1


def test_indications_raw_is_kept_alongside_the_mapped_group(dicts):
    row = make_raw_row(Indication=np.array(["Immunology"], dtype=object))
    df = normalize(raw_frame(row), dicts)
    deal = df.iloc[0]
    assert deal["indications_raw"] == ["Immunology"]
    assert deal["indications"] == ["INI"]


def test_deal_type_multi_group_counts_both_but_value_group_is_single(dicts):
    row = make_raw_row(**{"Deal Type": np.array(["License", "Investment"], dtype=object)})
    df = normalize(raw_frame(row), dicts)
    deal = df.iloc[0]
    assert set(deal["deal_type_groups"]) == {"License", "Investment"}
    assert deal["deal_type_group"] == "License"  # License outranks Investment


def test_mega_deal_threshold_is_inclusive(dicts):
    on_boundary = make_raw_row(record_id="rec_boundary", **{"Deals total $M": 10_000.0})
    below_boundary = make_raw_row(record_id="rec_below", **{"Deals total $M": 9_999.0})
    df = normalize(raw_frame(on_boundary, below_boundary), dicts)
    assert df.set_index("record_id").loc["rec_boundary", "is_mega_deal"]
    assert not df.set_index("record_id").loc["rec_below", "is_mega_deal"]


def test_year_derives_from_date_not_year_columns(dicts):
    # A stray "Year" or "Date years" column, if it ever appears in the raw frame,
    # must never be read -- year always comes from parsing Date.
    row = make_raw_row(Date="2019-03-01", Year="2099", **{"Date years": 1.0})
    df = normalize(raw_frame(row), dicts)
    assert df.iloc[0]["year"] == 2019


def test_investment_stage_irrelevant_becomes_none(dicts):
    row = make_raw_row(**{"Investment stage": "Irrelevant"})
    df = normalize(raw_frame(row), dicts)
    assert df.iloc[0]["investment_stage"] is None


def test_phase_unmapped_falls_back_to_unspecified(dicts):
    row = make_raw_row(**{"Development Phase on deal": "Some Weird Stage"})
    df = normalize(raw_frame(row), dicts)
    assert df.iloc[0]["phase"] == "Unspecified"


def test_disclosed_zero_upfront_is_not_treated_as_missing(dicts):
    row = make_raw_row(**{"Deals - Upfront $M": 0.0})
    df = normalize(raw_frame(row), dicts)
    deal = df.iloc[0]
    assert deal["upfront_musd"] == 0.0
    assert deal["has_disclosed_upfront"]


def test_missing_based_at_becomes_unknown(dicts):
    row = make_raw_row(**{"Based at:": None})
    df = normalize(raw_frame(row), dicts)
    assert df.iloc[0]["based_at"] == "Unknown"
