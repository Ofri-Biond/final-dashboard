import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from lib.models import SyncState

RAW_RECORDS_FILENAME = "deals_raw.parquet"
SYNC_STATE_FILENAME = "sync_state.json"


def save_raw_records(records: list[dict], cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    rows = [{"record_id": r["id"], **r["fields"]} for r in records]
    pd.DataFrame(rows).to_parquet(cache_dir / RAW_RECORDS_FILENAME, index=False)


def save_sync_state(state: SyncState, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_sync_at": state.last_sync_at.isoformat(),
        "row_count": state.row_count,
        "status": state.status,
        "error_message": state.error_message,
    }
    (cache_dir / SYNC_STATE_FILENAME).write_text(json.dumps(payload, indent=2))


def load_sync_state(cache_dir: Path) -> SyncState | None:
    path = cache_dir / SYNC_STATE_FILENAME
    if not path.exists():
        return None

    payload = json.loads(path.read_text())
    return SyncState(
        last_sync_at=datetime.fromisoformat(payload["last_sync_at"]),
        row_count=payload["row_count"],
        status=payload["status"],
        error_message=payload["error_message"],
    )
