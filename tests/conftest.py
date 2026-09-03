import numpy as np
import pandas as pd
import pytest

from lib.dictionaries import Dictionary

_MAPPINGS = {
    "technology": {
        "Multi-specific engager": ["Bispecific antibody", "Cell engager - T cell"],
        "CAR therapy": ["CAR T cells"],
        "Small molecule": ["Small Molecule"],
    },
    "deal_type": {
        "License": ["License"],
        "Investment": ["Investment"],
        "M&A": ["M&A"],
    },
    "indication": {
        "INI": ["INI", "Immunology"],
        "Oncology": ["Oncology"],
    },
    "geography": {"USA": ["USA"], "Europe": ["Europe"]},
    "phase": {
        "Preclinical": ["Preclinical", "Preclinical / Phase 1"],
        "Phase 1": ["Phase 1", "Phase 1b"],
        "Approved": ["Approved"],
    },
}


@pytest.fixture
def dicts() -> dict[str, Dictionary]:
    # Fresh instances per test so unmapped counters never leak between tests.
    return {name: Dictionary(name, mapping) for name, mapping in _MAPPINGS.items()}


def make_raw_row(**overrides) -> dict:
    """A minimal raw Airtable-shaped row; overrides replace individual fields.
    Fields omitted entirely (not even set to None) simulate Airtable's dropped keys."""
    row = {
        "record_id": "rec1",
        "Originator": "Acme Bio",
        "Collaborator": np.array(["BigPharma"], dtype=object),
        "Drug": "acme-101",
        "Indication": np.array(["Oncology"], dtype=object),
        "Technology": np.array(["Bispecific antibody", "Cell engager - T cell"], dtype=object),
        "Development Phase on deal": "Phase 1",
        "Deal Type": np.array(["License"], dtype=object),
        "Deals - Upfront $M": 100.0,
        "Deals total $M": 500.0,
        "Based at:": "USA",
        "Date": "2024-05-01",
        "Investment stage": "Irrelevant",
    }
    row.update(overrides)
    return row


def raw_frame(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows))
