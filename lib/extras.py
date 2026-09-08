"""News-intelligence context for the AI Market Brief. Reads the Airtable "Extras"
table (already synced to its own parquet by lib.data.load_extras) and selects the
handful of rows relevant to the current filtered view.

Companies/technologies are matched against the *same* vocabulary the deals table
uses (lib.dictionaries technology dictionary, and the deals' own collaborator/
originator values) so a match here means something to a reader of the charts.
"""

import json

import numpy as np
import pandas as pd

from lib.aggregate import explode
from lib.dictionaries import Dictionary
from lib.filters import FilterState

# Raw Airtable column names for the Extras table, kept next to their use so a
# rename is a one-line diff (same convention as lib/normalize.py).
_COL_TITLE = "Title"
_COL_URL = "URL"
_COL_DATE = "Date"
_COL_WHY = "Why it matters"
_COL_SCORE = "Score"
_COL_COMPANIES = "Companies mentioned"
_COL_CATEGORY = "Category"
_COL_TECHNOLOGY = "Technology"

EXTRAS_COLUMNS = [
    "record_id",
    "title",
    "url",
    "date",
    "why_it_matters",
    "score",
    "companies",
    "category",
    "technology_groups",
]

# Company tokens that show up in "Companies mentioned" but aren't real companies
# (and, worse, collide with real values in the deals' own collaborator universe --
# "ose" and "investors" are both live Airtable collaborator values). Dropping them
# here is what keeps the relevance match from firing on nearly every view.
EXTRAS_COMPANY_STOPLIST = {"ose", "investors"}

EXTRAS_MAX_ROWS = 15
WHY_IT_MATTERS_CHARS = 300


def _text(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


def _technology_tokens(value) -> list[str]:
    """The Technology column is multilineText holding a JSON-array *string*
    (e.g. '[\\n  "CAR T cells",\\n  " CD19"\\n]'), with messy whitespace/casing in
    the tokens themselves. Any parse failure -- missing, blank, malformed JSON,
    or not a list -- yields no tokens rather than raising.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(t).strip() for t in parsed if str(t).strip()]


def _company_tokens(value) -> list[str]:
    """"Companies mentioned" is an Airtable multipleSelects field -- a native
    array. But the parquet cache round-trip (lib.cache.save_raw_records) turns
    that into a numpy ndarray, the same trap lib/normalize.py:_list guards
    against for the deals table. Also accept a plain comma-joined string, in
    case a caller ever passes an unnormalized DataFrame straight from the API.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, (list, np.ndarray)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _normalize_row(row: pd.Series, technology: Dictionary) -> dict:
    date = pd.to_datetime(row.get(_COL_DATE), errors="coerce")

    tokens = [t.strip().lower() for t in _technology_tokens(row.get(_COL_TECHNOLOGY))]
    technology_groups = [technology.lookup(t) or t for t in tokens]

    companies = [
        c.strip().casefold()
        for c in _company_tokens(row.get(_COL_COMPANIES))
        if c.strip().casefold() not in EXTRAS_COMPANY_STOPLIST
    ]

    score = row.get(_COL_SCORE)
    score = 0.0 if score is None or (isinstance(score, float) and pd.isna(score)) else float(score)

    return {
        "record_id": row["record_id"],
        "title": _text(row.get(_COL_TITLE)) or "",
        "url": _text(row.get(_COL_URL)),
        "date": date.date() if pd.notna(date) else None,
        "why_it_matters": _text(row.get(_COL_WHY)) or "",
        "score": score,
        "companies": companies,
        "category": _text(row.get(_COL_CATEGORY)) or "other",
        "technology_groups": technology_groups,
    }


def normalize_extras(raw: pd.DataFrame, technology: Dictionary) -> pd.DataFrame:
    """Turn the raw Extras Airtable frame into one row per news item."""
    if raw.empty:
        return pd.DataFrame(columns=EXTRAS_COLUMNS)
    rows = [_normalize_row(row, technology) for _, row in raw.iterrows()]
    return pd.DataFrame(rows, columns=EXTRAS_COLUMNS)


def get_extras_context(
    df_filtered: pd.DataFrame,
    filters: FilterState,
    extras: pd.DataFrame | None = None,
) -> list[dict]:
    """News rows relevant to the current filtered view: technology overlap with
    the filtered deals' technology groups, OR company overlap with the filtered
    deals' originators/collaborators (casefolded), AND (when a year filter is
    active) the news item's own date falls inside that year range. No matches
    -> [] -- the brief then runs on the fact pack alone with no mention of news.

    Ranked by score desc, then date desc; capped at EXTRAS_MAX_ROWS. Each dict
    carries every normalized field (including record_id and score, needed by the
    UI and the brief cache key) -- lib.brief projects this down to the few
    fields the model is allowed to see.
    """
    if extras is None:
        from lib.data import load_extras

        extras = load_extras()
    if extras.empty:
        return []

    tech_scope = {t.casefold() for values in df_filtered["technologies"] for t in values}

    originators = {str(o).casefold() for o in df_filtered["originator"].dropna()}
    collaborators = {
        str(c).casefold() for c in explode(df_filtered, "collaborators")["collaborators"]
    }
    company_scope = (originators | collaborators) - EXTRAS_COMPANY_STOPLIST

    year_range = (min(filters.years), max(filters.years)) if filters.years else None

    matched = []
    for row in extras.to_dict("records"):
        if year_range is not None:
            out_of_range = row["date"] is None or not (
                year_range[0] <= row["date"].year <= year_range[1]
            )
            if out_of_range:
                continue
        row_tech = {g.casefold() for g in row["technology_groups"]}
        row_companies = {c.casefold() for c in row["companies"]}
        if not (row_tech & tech_scope) and not (row_companies & company_scope):
            continue
        matched.append(row)

    matched.sort(key=lambda r: (r["score"], r["date"] or pd.Timestamp.min.date()), reverse=True)
    return matched[:EXTRAS_MAX_ROWS]
