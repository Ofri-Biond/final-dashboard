import pandas as pd

from lib.filters import FilterState, apply_filters, most_restrictive, previous_period


def test_url_round_trip_preserves_state():
    state = FilterState(
        years=(2023, 2025),
        quarters=(3, 4),
        indications=("Oncology", "INI"),
        indications_raw=("Immunology",),
        technologies=("Antibody Drug Conjugate",),
        technologies_raw=("ADCs",),
        deal_types_raw=("Co-development", "Option to license"),
        exclude_mega_deals=False,
    )
    restored = FilterState.from_query(state.to_query())
    assert restored == state


def test_default_state_produces_empty_query():
    assert FilterState().to_query() == {}


def test_malformed_query_falls_back_to_defaults():
    restored = FilterState.from_query(
        {"years": "not-a-year", "quarters": "not-a-quarter", "exclude_mega_deals": "??"}
    )
    assert restored == FilterState(exclude_mega_deals=True)


def test_active_count_reflects_non_default_fields():
    assert FilterState().active_count == 0
    assert FilterState(years=(2023, 2024)).active_count == 1
    assert FilterState(years=(2023, 2024), technologies=("ADC",)).active_count == 2
    assert FilterState(quarters=(3, 4)).active_count == 1
    assert FilterState(exclude_mega_deals=False).active_count == 1


def _deals_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_id": "a",
                "year": 2023,
                "quarter": 1,
                "technologies": ["ADC"],
                "technologies_raw": ["Antibody Drug Conjugate"],
                "indications": ["Oncology"],
                "indications_raw": ["Oncology"],
                "based_at": "USA",
                "phase": "Phase 1",
                "deal_type_groups": ["License"],
                "deal_types": ["Co-development"],
            },
            {
                "record_id": "b",
                "year": 2024,
                "quarter": 3,
                "technologies": ["Small molecule"],
                "technologies_raw": ["Small Molecule"],
                "indications": ["INI"],
                "indications_raw": ["Immunology"],
                "based_at": "China",
                "phase": "Phase 2",
                "deal_type_groups": ["License"],
                "deal_types": ["Option to license"],
            },
            {
                "record_id": "c",
                "year": None,
                "quarter": None,
                "technologies": ["ADC"],
                "technologies_raw": ["ADCs"],  # same group as a, different raw token
                "indications": ["INI"],
                "indications_raw": ["INI"],  # same group as b, different raw token
                "based_at": "USA",
                "phase": "Phase 1",
                "deal_type_groups": ["Investment"],
                "deal_types": ["Investment"],
            },
        ]
    )


def test_year_filter_never_drops_undated_rows():
    df = _deals_frame()
    result = apply_filters(df, FilterState(years=(2024,)))
    assert set(result["record_id"]) == {"b", "c"}  # b matches the year, c is undated


def test_year_filter_accepts_a_discontiguous_set_of_specific_years():
    df = _deals_frame()
    result = apply_filters(df, FilterState(years=(2023,)))
    assert set(result["record_id"]) == {"a", "c"}  # a matches, c is undated


def test_quarter_filter_never_drops_rows_with_no_quarter():
    df = _deals_frame()
    result = apply_filters(df, FilterState(quarters=(3,)))
    assert set(result["record_id"]) == {"b", "c"}  # b matches, c has no quarter


def test_year_and_quarter_filters_combine_with_and():
    df = _deals_frame()
    result = apply_filters(df, FilterState(years=(2024,), quarters=(3,)))
    assert set(result["record_id"]) == {"b", "c"}  # b matches both, c is undated


def test_list_column_filter_matches_on_overlap():
    df = _deals_frame()
    result = apply_filters(df, FilterState(technologies=("ADC",)))
    assert set(result["record_id"]) == {"a", "c"}


def test_scalar_column_filter_matches_membership():
    df = _deals_frame()
    result = apply_filters(df, FilterState(geographies=("China",)))
    assert set(result["record_id"]) == {"b"}


def test_deal_type_group_filter_matches_both_raw_types_under_it():
    df = _deals_frame()
    result = apply_filters(df, FilterState(deal_types=("License",)))
    assert set(result["record_id"]) == {"a", "b"}  # both roll up to License


def test_deal_type_raw_filter_isolates_one_raw_type_within_a_group():
    df = _deals_frame()
    result = apply_filters(df, FilterState(deal_types_raw=("Co-development",)))
    assert set(result["record_id"]) == {"a"}  # not b, though both are "License"


def test_deal_type_group_and_raw_filters_combine_with_and():
    df = _deals_frame()
    result = apply_filters(
        df, FilterState(deal_types=("License",), deal_types_raw=("Option to license",))
    )
    assert set(result["record_id"]) == {"b"}


def test_technology_raw_filter_isolates_one_raw_token_within_a_group():
    df = _deals_frame()
    result = apply_filters(df, FilterState(technologies_raw=("Antibody Drug Conjugate",)))
    assert set(result["record_id"]) == {"a"}  # not c, though both map to "ADC"


def test_indication_raw_filter_isolates_one_raw_token_within_a_group():
    df = _deals_frame()
    result = apply_filters(df, FilterState(indications_raw=("Immunology",)))
    assert set(result["record_id"]) == {"b"}  # not c, though both map to "INI"


def test_previous_period_same_length_window_immediately_before():
    prev = previous_period(FilterState(years=(2024, 2025)), data_years=(2020, 2025))
    assert prev == FilterState(years=(2022, 2023))


def test_previous_period_falls_back_to_data_range_when_no_year_filter():
    prev = previous_period(FilterState(), data_years=(2020, 2023))
    # full range is 2020-2023 (length 4); prior window would be 2016-2019, all before
    # the data starts -- clamped, not None, since 2019 >= ... wait: prev_end=2019 >= 2020? no.
    assert prev is None


def test_previous_period_none_when_no_room_before_data_start():
    prev = previous_period(FilterState(years=(2020, 2021)), data_years=(2020, 2025))
    assert prev is None


def test_previous_period_clamps_to_a_partial_window_at_the_data_boundary():
    prev = previous_period(FilterState(years=(2021, 2022)), data_years=(2020, 2025))
    assert prev == FilterState(years=(2020,))  # only one prior year exists


def test_previous_period_preserves_other_filter_fields():
    filters = FilterState(years=(2024, 2025), technologies=("ADC",))
    prev = previous_period(filters, data_years=(2020, 2025))
    assert prev.technologies == ("ADC",)


def test_most_restrictive_ranks_by_rows_removed():
    df = _deals_frame()
    # technologies=("ADC",) removes 1 row (b); geographies=("China",) removes 2 (a, c)
    filters = FilterState(technologies=("ADC",), geographies=("China",))
    result = most_restrictive(df, filters, n=2)
    assert result == ["Geography", "Technology"]


def test_most_restrictive_respects_n():
    df = _deals_frame()
    filters = FilterState(technologies=("ADC",), geographies=("China",), phases=("Phase 1",))
    result = most_restrictive(df, filters, n=1)
    assert len(result) == 1
