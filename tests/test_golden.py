"""
The R1 gate (PRD risk: "normalization is where trust dies"): every count here should
reproduce the BD deck's slide 16 (deal-type mix) and slide 17 (technology counts).

The deck isn't in the repo yet, so the constants below are a snapshot computed from
the live Airtable cache -- they pin today's grouping rules so a dictionary edit that
shifts a count fails loudly. When the real deck numbers are available, replace this
block (and only this block) with them; no other file needs to change.
"""

from pathlib import Path

import pandas as pd
import pytest

from lib.aggregate import aggregate
from lib.dictionaries import load_dictionaries
from lib.normalize import normalize

RAW_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "cache" / "deals_raw.parquet"
DICTIONARIES_DIR = Path(__file__).resolve().parent.parent / "config" / "dictionaries"

EXPECTED_ROW_COUNT = 673
EXPECTED_DATED = 485
EXPECTED_UNDATED = 188

EXPECTED_MEGA_DEALS = {
    "Seagen": 43000.0,
    "Immmunomedics": 21000.0,
    "Hengrui Pharma, paying": 15000.0,
    "Immunogen": 10000.0,
}

EXPECTED_TECHNOLOGY_COUNTS = {
    "Small molecule": 137,
    "Monoclonal antibody": 111,
    "Multi-specific engager": 107,
    "Antibody Drug Conjugate": 95,
    "Platform": 68,
    "CAR therapy": 52,
    "Protein degrader": 44,
    "Radiotherapy": 27,
}

EXPECTED_DEAL_TYPE_GROUP_COUNTS = {
    "License": 294,
    "Investment": 249,
    "M&A": 91,
    "Other": 31,
    "IPO": 17,
}


@pytest.fixture(scope="module")
def deals() -> pd.DataFrame:
    if not RAW_CACHE_PATH.exists():
        pytest.skip("no cached data -- run `python scripts/sync.py` first")
    raw = pd.read_parquet(RAW_CACHE_PATH)
    dicts = load_dictionaries(DICTIONARIES_DIR)
    return normalize(raw, dicts)


def test_row_count(deals):
    assert len(deals) == EXPECTED_ROW_COUNT


def test_dated_vs_undated_split(deals):
    assert deals["year"].notna().sum() == EXPECTED_DATED
    assert deals["year"].isna().sum() == EXPECTED_UNDATED


def test_mega_deals_are_exactly_the_expected_four(deals):
    mega = deals[deals["is_mega_deal"]]
    assert len(mega) == len(EXPECTED_MEGA_DEALS)
    actual = dict(zip(mega["originator"], mega["total_musd"], strict=True))
    assert actual == EXPECTED_MEGA_DEALS


def test_technology_group_counts_match_snapshot(deals):
    result = aggregate(deals, by="technologies", measure="count").frame
    counts = dict(zip(result["technologies"], result["value"], strict=True))
    for group, expected_count in EXPECTED_TECHNOLOGY_COUNTS.items():
        actual_count = counts.get(group)
        message = f"{group}: expected {expected_count}, got {actual_count}"
        assert actual_count == expected_count, message


def test_deal_type_group_counts_match_snapshot(deals):
    result = aggregate(deals, by="deal_type_groups", measure="count").frame
    counts = dict(zip(result["deal_type_groups"], result["value"], strict=True))
    assert counts == EXPECTED_DEAL_TYPE_GROUP_COUNTS
