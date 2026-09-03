from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import Literal


@dataclass
class SyncState:
    last_sync_at: datetime
    row_count: int
    status: Literal["ok", "stale", "failed"]
    error_message: str | None = None


PHASE_ORDER = [
    "Discovery",
    "Preclinical",
    "IND",
    "Phase 1",
    "Phase 1/2",
    "Phase 2",
    "Phase 2/3",
    "Phase 3",
    "Submitted",
    "Approved",
    "Marketed",
    "Unspecified",
]

MEGA_DEAL_THRESHOLD_MUSD = 10_000

# Priority for deal_type_group when a row has multiple deal types: the row's value
# aggregates count once, under the highest-priority group it belongs to.
DEAL_TYPE_GROUP_PRIORITY = ["M&A", "License", "Investment", "IPO", "Other"]


@dataclass
class Deal:
    record_id: str
    originator: str | None
    collaborators: list[str]
    drug: str | None
    indications_raw: list[str]
    indications: list[str]
    specific_indication: str | None
    target: str | None
    technologies_raw: list[str]
    technologies: list[str]
    phase_raw: str | None
    phase: str | None
    maturity: str | None
    asset_type: str | None
    deal_types: list[str]
    # deal_type_groups drives count charts (a multi-type row counts in every group it
    # belongs to); deal_type_group drives value charts (a row's value counts once,
    # under its single highest-priority group). See DEAL_TYPE_GROUP_PRIORITY.
    deal_type_groups: list[str]
    deal_type_group: str
    investment_stage: str | None
    upfront_musd: float | None
    total_musd: float | None
    total_detail: str | None
    based_at: str | None
    deal_date: date | None
    year: int | None
    quarter: int | None
    source_url: str | None
    related_publications: str | None
    comment: str | None
    needs_review: bool
    review_notes: str | None
    auto_loaded: bool
    is_mega_deal: bool
    has_disclosed_upfront: bool
    has_disclosed_total: bool


DEAL_COLUMNS = [f.name for f in fields(Deal)]
