"""Fetch the Airtable table into the local raw cache. Run: python scripts/sync.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.data import sync_extras_now, sync_now


def main() -> int:
    state = sync_now()
    if state.status == "failed":
        print(f"Sync failed: {state.error_message}", file=sys.stderr)
        return 1
    print(f"Synced {state.row_count} rows")

    sync_extras_now()  # news intelligence for the AI brief; never raises
    print("Synced Extras (news intelligence)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
