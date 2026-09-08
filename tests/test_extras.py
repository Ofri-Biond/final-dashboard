import numpy as np
import pandas as pd

from lib.extras import (
    EXTRAS_COMPANY_STOPLIST,
    EXTRAS_MAX_ROWS,
    get_extras_context,
    normalize_extras,
)
from lib.filters import FilterState
from tests.conftest import extras_frame, make_extras_row


def _deals_frame(technologies=None, originator=None, collaborators=None, based_at="USA"):
    return pd.DataFrame([{
        "technologies": technologies or [],
        "originator": originator,
        "collaborators": collaborators or [],
        "based_at": based_at,
    }])


def test_malformed_technology_json_yields_no_tokens_not_a_crash(dicts):
    raw = extras_frame(make_extras_row(Technology="not valid json"))
    normalized = normalize_extras(raw, dicts["technology"])
    assert normalized.loc[0, "technology_groups"] == []


def test_missing_technology_field_yields_no_tokens(dicts):
    raw = extras_frame(make_extras_row(Technology=None))
    normalized = normalize_extras(raw, dicts["technology"])
    assert normalized.loc[0, "technology_groups"] == []


def test_technology_tokens_are_stripped_and_lowercased_before_mapping(dicts):
    raw = extras_frame(make_extras_row(Technology='[" t cell", "Bispecific antibody"]'))
    normalized = normalize_extras(raw, dicts["technology"])
    groups = normalized.loc[0, "technology_groups"]
    # "Bispecific antibody" maps to the dictionary's canonical group; the unknown
    # " t cell" token passes through, stripped and lowercased, under its own label.
    assert "Multi-specific engager" in groups
    assert "t cell" in groups


def test_known_technology_token_maps_through_the_same_dictionary_as_deals(dicts):
    raw = extras_frame(make_extras_row(Technology='["CAR T cells"]'))
    normalized = normalize_extras(raw, dicts["technology"])
    assert normalized.loc[0, "technology_groups"] == ["CAR therapy"]


def test_stoplist_drops_noise_company_tokens(dicts):
    raw = extras_frame(
        make_extras_row(**{"Companies mentioned": np.array(["ose", "investors", "Novartis"], dtype=object)})
    )
    normalized = normalize_extras(raw, dicts["technology"])
    assert normalized.loc[0, "companies"] == ["novartis"]
    assert EXTRAS_COMPANY_STOPLIST == {"ose", "investors"}


def test_companies_parsed_from_a_comma_string_too(dicts):
    raw = extras_frame(make_extras_row(**{"Companies mentioned": "Novartis, Ose, BMS"}))
    normalized = normalize_extras(raw, dicts["technology"])
    assert normalized.loc[0, "companies"] == ["novartis", "bms"]


def test_companies_survive_a_real_parquet_round_trip(dicts, tmp_path):
    """The Extras cache is a parquet file (lib.cache.save_raw_records), which
    turns a native Airtable array into a numpy ndarray -- the same trap
    lib/normalize.py:_list guards against for the deals table. If
    normalize_extras only accepted a plain list, every row would silently lose
    its companies after one round-trip through the cache.
    """
    raw = pd.DataFrame([{
        "record_id": "extra1",
        "Title": "t", "URL": "u", "Date": "2026-08-15", "Why it matters": "w",
        "Score": 0.5, "Companies mentioned": ["Novartis", "BMS"],
        "Category": "readout", "Technology": "[]",
    }])
    path = tmp_path / "extras_raw.parquet"
    raw.to_parquet(path, index=False)
    round_tripped = pd.read_parquet(path)

    assert isinstance(round_tripped.loc[0, "Companies mentioned"], np.ndarray)
    normalized = normalize_extras(round_tripped, dicts["technology"])
    assert normalized.loc[0, "companies"] == ["novartis", "bms"]


def test_score_missing_defaults_to_zero(dicts):
    raw = extras_frame(make_extras_row(Score=None))
    normalized = normalize_extras(raw, dicts["technology"])
    assert normalized.loc[0, "score"] == 0.0


def test_category_missing_defaults_to_other(dicts):
    raw = extras_frame(make_extras_row(Category=None))
    normalized = normalize_extras(raw, dicts["technology"])
    assert normalized.loc[0, "category"] == "other"


def test_technology_overlap_selects_a_row(dicts):
    extras = normalize_extras(
        extras_frame(make_extras_row(Technology='["CAR T cells"]', **{"Companies mentioned": []})),
        dicts["technology"],
    )
    deals = _deals_frame(technologies=["CAR therapy"])
    matched = get_extras_context(deals, FilterState(), extras=extras)
    assert len(matched) == 1


def test_company_overlap_selects_a_row(dicts):
    extras = normalize_extras(
        extras_frame(make_extras_row(Technology="[]", **{"Companies mentioned": np.array(["Novartis"])})),
        dicts["technology"],
    )
    deals = _deals_frame(collaborators=["Novartis"])
    matched = get_extras_context(deals, FilterState(), extras=extras)
    assert len(matched) == 1


def test_no_overlap_returns_empty_list(dicts):
    extras = normalize_extras(
        extras_frame(make_extras_row(Technology='["Peptide"]', **{"Companies mentioned": np.array(["Nobody"])})),
        dicts["technology"],
    )
    deals = _deals_frame(technologies=["Small molecule"], collaborators=["SomeCo"])
    matched = get_extras_context(deals, FilterState(), extras=extras)
    assert matched == []


def test_year_gate_excludes_out_of_range_news(dicts):
    extras = normalize_extras(
        extras_frame(make_extras_row(Technology='["CAR T cells"]', Date="2020-01-01")),
        dicts["technology"],
    )
    deals = _deals_frame(technologies=["CAR therapy"])
    matched = get_extras_context(deals, FilterState(years=(2024, 2025)), extras=extras)
    assert matched == []


def test_year_gate_allows_matching_year(dicts):
    extras = normalize_extras(
        extras_frame(make_extras_row(Technology='["CAR T cells"]', Date="2024-06-01")),
        dicts["technology"],
    )
    deals = _deals_frame(technologies=["CAR therapy"])
    matched = get_extras_context(deals, FilterState(years=(2024, 2025)), extras=extras)
    assert len(matched) == 1


def test_no_year_filter_skips_the_gate(dicts):
    extras = normalize_extras(
        extras_frame(make_extras_row(Technology='["CAR T cells"]', Date="2010-01-01")),
        dicts["technology"],
    )
    deals = _deals_frame(technologies=["CAR therapy"])
    matched = get_extras_context(deals, FilterState(), extras=extras)
    assert len(matched) == 1


def test_results_ranked_by_score_desc_then_date_desc_and_capped(dicts):
    rows = []
    for i in range(20):
        rows.append(make_extras_row(
            record_id=f"extra{i}",
            Technology='["CAR T cells"]',
            Score=0.5,
            Date=f"2026-01-{(i % 28) + 1:02d}",
        ))
    # one clearly-highest-scored row to check it sorts first
    rows.append(make_extras_row(record_id="best", Technology='["CAR T cells"]', Score=0.99, Date="2026-01-01"))
    extras = normalize_extras(extras_frame(*rows), dicts["technology"])
    deals = _deals_frame(technologies=["CAR therapy"])

    matched = get_extras_context(deals, FilterState(), extras=extras)

    assert len(matched) == EXTRAS_MAX_ROWS
    assert matched[0]["record_id"] == "best"
    scores_and_dates = [(r["score"], r["date"]) for r in matched]
    assert scores_and_dates == sorted(scores_and_dates, reverse=True)
