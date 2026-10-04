import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from lib.airtable import AirtableClient
from lib.cache import (
    EXTRAS_RECORDS_FILENAME,
    RAW_RECORDS_FILENAME,
    load_sync_state,
    save_raw_records,
    save_sync_state,
)
from lib.config import REPO_ROOT, load_cache_dir, load_settings
from lib.dictionaries import Dictionary, load_dictionaries, write_unmapped_log
from lib.extras import EXTRAS_COLUMNS, normalize_extras
from lib.models import DEAL_COLUMNS, SyncState
from lib.normalize import normalize

logger = logging.getLogger(__name__)

DICTIONARIES_DIR = REPO_ROOT / "config" / "dictionaries"
UNMAPPED_LOG_FILENAME = "unmapped_values.csv"


class DataError(Exception):
    pass


@st.cache_resource
def _load_dictionaries_cached() -> dict[str, Dictionary]:
    return load_dictionaries(DICTIONARIES_DIR)


def _is_current(dicts: dict[str, Dictionary]) -> bool:
    # cache_resource is keyed on the cached function's own source, so after a code
    # change to Dictionary (e.g. a hot redeploy) it keeps serving instances of the
    # *old* class. Those fail isinstance against the reloaded class.
    return all(isinstance(d, Dictionary) and hasattr(d, "categories") for d in dicts.values())


def _dictionaries() -> dict[str, Dictionary]:
    dicts = _load_dictionaries_cached()
    if not _is_current(dicts):
        logger.warning("Cached dictionaries are stale (code changed); reloading them")
        _load_dictionaries_cached.clear()
        dicts = _load_dictionaries_cached()
    return dicts


def dictionary_categories(name: str) -> frozenset[str]:
    """The main categories defined in config/dictionaries/<name>.yaml. Never
    raises -- an unknown/broken dictionary yields no categories, so a filter
    shows no options rather than taking the page down."""
    try:
        return _dictionaries()[name].categories
    except Exception:
        logger.exception("Could not read categories for dictionary %r", name)
        return frozenset()


def load_deals() -> pd.DataFrame:
    """Cached deals, guarded against a stale cache entry. cache_data is keyed on
    _load_deals_cached's source only, so after normalize()/DEAL_COLUMNS change a
    frame from the old code can still be served; it is dropped and rebuilt once.
    """
    deals = _load_deals_cached()
    missing = set(DEAL_COLUMNS) - set(deals.columns)
    if missing:
        logger.warning("Cached deals are missing columns %s; rebuilding", sorted(missing))
        _load_deals_cached.clear()
        deals = _load_deals_cached()
        missing = set(DEAL_COLUMNS) - set(deals.columns)
        if missing:
            raise DataError(f"Deals data is missing expected columns: {', '.join(sorted(missing))}")
    return deals


def clear_deals_cache() -> None:
    _load_deals_cached.clear()


@st.cache_data(ttl=900)
def _load_deals_cached() -> pd.DataFrame:
    settings = load_settings()
    raw_path = settings.cache_dir / RAW_RECORDS_FILENAME
    if not raw_path.exists():
        # A fresh deploy (e.g. Streamlit Cloud) starts with no cache checked into the
        # repo -- pull once from Airtable instead of crashing before the UI renders.
        sync_now()
        if not raw_path.exists():
            raise DataError(
                f"No cached data at {raw_path} and the initial Airtable sync failed. "
                "Check AIRTABLE_PAT/AIRTABLE_BASE_ID in secrets, then use the Refresh "
                "button once they're fixed."
            )

    raw = pd.read_parquet(raw_path)
    dicts = _dictionaries()
    for dictionary in dicts.values():
        dictionary.unmapped.clear()  # dicts are cached across reruns; counts must not accumulate
    deals = normalize(raw, dicts)
    write_unmapped_log(dicts, Path(settings.cache_dir) / UNMAPPED_LOG_FILENAME)
    return deals


@st.cache_data(ttl=900)
def load_extras() -> pd.DataFrame:
    """News-intelligence rows for the AI brief. Unlike load_deals, this never
    raises -- a missing/failed sync degrades to an empty frame (matching
    EXTRAS_COLUMNS) so the brief card can still render on the numbers alone.
    """
    settings = load_settings()
    raw_path = settings.cache_dir / EXTRAS_RECORDS_FILENAME
    if not raw_path.exists():
        sync_extras_now()
        if not raw_path.exists():
            return pd.DataFrame(columns=EXTRAS_COLUMNS)

    try:
        raw = pd.read_parquet(raw_path)
        return normalize_extras(raw, _dictionaries()["technology"])
    except Exception:
        logger.exception("Could not load news extras; continuing without them")
        return pd.DataFrame(columns=EXTRAS_COLUMNS)


def get_sync_state() -> SyncState | None:
    return load_sync_state(load_cache_dir())


def sync_now() -> SyncState:
    """Pull the Airtable table into the local cache. Never raises -- a failure
    (including missing credentials) is recorded as status="failed" and the last
    good cache stays in place, so the UI can keep serving stale data with a banner
    rather than crash (PRD "Airtable down").
    """
    cache_dir = load_cache_dir()
    try:
        settings = load_settings()
        client = AirtableClient(pat=settings.airtable_pat, base_id=settings.airtable_base_id)
        records = client.fetch_all_records(settings.airtable_table_id)
        save_raw_records(records, cache_dir)
        state = SyncState(last_sync_at=datetime.now(), row_count=len(records), status="ok")
    except Exception as exc:
        logger.exception("Airtable sync failed")
        state = SyncState(
            last_sync_at=datetime.now(), row_count=0, status="failed", error_message=str(exc)
        )

    try:
        save_sync_state(state, cache_dir)
    except OSError:
        logger.exception("Could not write the sync state file")
    return state


def sync_extras_now() -> None:
    """Pull the Extras (news intelligence) table into its own cache file. Never
    raises and has no separate SyncState -- a failure here should not make the
    freshness banner (which is about the deals table) look broken; the AI brief
    card simply runs with fewer or no news rows until the next successful sync.
    """
    try:
        settings = load_settings()
        client = AirtableClient(pat=settings.airtable_pat, base_id=settings.airtable_base_id)
        records = client.fetch_all_records(settings.airtable_extras_table_id)
        save_raw_records(records, settings.cache_dir, filename=EXTRAS_RECORDS_FILENAME)
    except Exception:
        logger.exception("Extras sync failed")


def reset_caches() -> None:
    """Drop every Streamlit cache (data + resources) -- the recovery path when a
    stale cache entry is the problem."""
    st.cache_data.clear()
    st.cache_resource.clear()
