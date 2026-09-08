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
from lib.config import REPO_ROOT, load_settings
from lib.dictionaries import load_dictionaries, write_unmapped_log
from lib.extras import EXTRAS_COLUMNS, normalize_extras
from lib.models import SyncState
from lib.normalize import normalize

DICTIONARIES_DIR = REPO_ROOT / "config" / "dictionaries"
UNMAPPED_LOG_FILENAME = "unmapped_values.csv"


class DataError(Exception):
    pass


@st.cache_resource
def _dictionaries():
    return load_dictionaries(DICTIONARIES_DIR)


@st.cache_data(ttl=900)
def load_deals() -> pd.DataFrame:
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

    raw = pd.read_parquet(raw_path)
    technology_dict = _dictionaries()["technology"]
    return normalize_extras(raw, technology_dict)


def get_sync_state() -> SyncState | None:
    settings = load_settings()
    return load_sync_state(settings.cache_dir)


def sync_now() -> SyncState:
    """Pull the Airtable table into the local cache. Never raises -- a failure is
    recorded as status="failed" and the last good cache stays in place, so the UI
    can keep serving stale data with a banner rather than crash (PRD "Airtable down").
    """
    settings = load_settings()
    client = AirtableClient(pat=settings.airtable_pat, base_id=settings.airtable_base_id)

    try:
        records = client.fetch_all_records(settings.airtable_table_id)
    except Exception as exc:
        state = SyncState(
            last_sync_at=datetime.now(), row_count=0, status="failed", error_message=str(exc)
        )
        save_sync_state(state, settings.cache_dir)
        return state

    save_raw_records(records, settings.cache_dir)
    state = SyncState(last_sync_at=datetime.now(), row_count=len(records), status="ok")
    save_sync_state(state, settings.cache_dir)
    return state


def sync_extras_now() -> None:
    """Pull the Extras (news intelligence) table into its own cache file. Never
    raises and has no separate SyncState -- a failure here should not make the
    freshness banner (which is about the deals table) look broken; the AI brief
    card simply runs with fewer or no news rows until the next successful sync.
    """
    settings = load_settings()
    client = AirtableClient(pat=settings.airtable_pat, base_id=settings.airtable_base_id)

    try:
        records = client.fetch_all_records(settings.airtable_extras_table_id)
    except Exception:
        return

    save_raw_records(records, settings.cache_dir, filename=EXTRAS_RECORDS_FILENAME)
