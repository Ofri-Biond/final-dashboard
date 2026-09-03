import numpy as np
import pandas as pd

from lib.dictionaries import Dictionary
from lib.models import DEAL_TYPE_GROUP_PRIORITY, MEGA_DEAL_THRESHOLD_MUSD, PHASE_ORDER

# Raw Airtable column names, kept next to their use so a rename is a one-line diff.
_COL_ORIGINATOR = "Originator"
_COL_COLLABORATOR = "Collaborator"
_COL_DRUG = "Drug"
_COL_INDICATION = "Indication"
_COL_SPECIFIC_INDICATION = "Specific indication"
_COL_TARGET = "Target"
_COL_TECHNOLOGY = "Technology"
_COL_PHASE = "Development Phase on deal"
_COL_MATURITY = "product maturity"
_COL_TYPE = "Type"
_COL_DEAL_TYPE = "Deal Type"
_COL_INVESTMENT_STAGE = "Investment stage"
_COL_UPFRONT = "Deals - Upfront $M"
_COL_TOTAL = "Deals total $M"
_COL_TOTAL_DETAIL = "Deals total detail"
_COL_BASED_AT = "Based at:"
_COL_DATE = "Date"
_COL_SOURCE_URL = "LInks for Yaniv"
_COL_RELATED_PUBLICATIONS = "Related publications"
_COL_COMMENT = "Comment"
_COL_NEEDS_REVIEW = "Needs review"
_COL_REVIEW_NOTES = "Review notes"
_COL_AUTO_LOADED = "Auto-loaded"

# NOTE: the table's "Year" (single select) and "Date years" (number) columns are
# never read. Both are separately-maintained fields that can drift from "Date";
# `year` is always derived from `deal_date` so there is exactly one source of truth.
# `quarter` (1-4) is likewise always derived from `deal_date`.


def _text(row: pd.Series, col: str) -> str | None:
    value = row.get(col)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


def _number(row: pd.Series, col: str) -> float | None:
    value = row.get(col)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return float(value)


def _flag(row: pd.Series, col: str) -> bool:
    value = row.get(col)
    return bool(value) and not (isinstance(value, float) and pd.isna(value))


def _list(row: pd.Series, col: str) -> list[str]:
    value = row.get(col)
    if not isinstance(value, np.ndarray):
        return []
    return [str(v).strip() for v in value]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        seen[v] = None
    return list(seen)


def _map_list(values: list[str], dictionary: Dictionary) -> list[str]:
    return _dedupe_preserve_order([dictionary.map(v) for v in values])


def _deal_type_group(groups: list[str]) -> str:
    for candidate in DEAL_TYPE_GROUP_PRIORITY:
        if candidate in groups:
            return candidate
    return "Other"


def _normalize_row(row: pd.Series, dicts: dict[str, Dictionary]) -> dict:
    technologies_raw = _list(row, _COL_TECHNOLOGY)
    technologies = _map_list(technologies_raw, dicts["technology"])

    deal_types = _list(row, _COL_DEAL_TYPE)
    deal_type_groups = _map_list(deal_types, dicts["deal_type"])
    deal_type_group = _deal_type_group(deal_type_groups)

    indications_raw = _list(row, _COL_INDICATION)
    indications = _map_list(indications_raw, dicts["indication"])

    phase_raw = _text(row, _COL_PHASE)
    mapped_phase = dicts["phase"].map(phase_raw) if phase_raw is not None else "Unspecified"
    # PHASE_ORDER is a closed enum (US10) -- unlike other dictionaries, a phase that
    # isn't in it collapses to "Unspecified" rather than passing through raw text.
    # It is still recorded as unmapped by Dictionary.map above, for the review log.
    phase = mapped_phase if mapped_phase in PHASE_ORDER else "Unspecified"

    based_at_raw = _text(row, _COL_BASED_AT)
    based_at = dicts["geography"].map(based_at_raw) if based_at_raw is not None else "Unknown"

    deal_date = pd.to_datetime(row.get(_COL_DATE), errors="coerce")
    year = int(deal_date.year) if pd.notna(deal_date) else None
    quarter = int((deal_date.month - 1) // 3 + 1) if pd.notna(deal_date) else None

    upfront_musd = _number(row, _COL_UPFRONT)
    total_musd = _number(row, _COL_TOTAL)

    investment_stage = _text(row, _COL_INVESTMENT_STAGE)
    if investment_stage == "Irrelevant":
        investment_stage = None

    return {
        "record_id": row["record_id"],
        "originator": _text(row, _COL_ORIGINATOR),
        "collaborators": _list(row, _COL_COLLABORATOR),
        "drug": _text(row, _COL_DRUG),
        "indications_raw": indications_raw,
        "indications": indications,
        "specific_indication": _text(row, _COL_SPECIFIC_INDICATION),
        "target": _text(row, _COL_TARGET),
        "technologies_raw": technologies_raw,
        "technologies": technologies,
        "phase_raw": phase_raw,
        "phase": phase,
        "maturity": _text(row, _COL_MATURITY),
        "asset_type": _text(row, _COL_TYPE),
        "deal_types": deal_types,
        "deal_type_groups": deal_type_groups,
        "deal_type_group": deal_type_group,
        "investment_stage": investment_stage,
        "upfront_musd": upfront_musd,
        "total_musd": total_musd,
        "total_detail": _text(row, _COL_TOTAL_DETAIL),
        "based_at": based_at,
        "deal_date": deal_date.date() if pd.notna(deal_date) else None,
        "year": year,
        "quarter": quarter,
        "source_url": _text(row, _COL_SOURCE_URL),
        "related_publications": _text(row, _COL_RELATED_PUBLICATIONS),
        "comment": _text(row, _COL_COMMENT),
        "needs_review": _flag(row, _COL_NEEDS_REVIEW),
        "review_notes": _text(row, _COL_REVIEW_NOTES),
        "auto_loaded": _flag(row, _COL_AUTO_LOADED),
        "is_mega_deal": total_musd is not None and total_musd >= MEGA_DEAL_THRESHOLD_MUSD,
        "has_disclosed_upfront": upfront_musd is not None,
        "has_disclosed_total": total_musd is not None,
    }


def normalize(raw: pd.DataFrame, dicts: dict[str, Dictionary]) -> pd.DataFrame:
    """Turn the raw Airtable frame into one row per Deal field (see lib.models.Deal)."""
    rows = [_normalize_row(row, dicts) for _, row in raw.iterrows()]
    return pd.DataFrame(rows)
