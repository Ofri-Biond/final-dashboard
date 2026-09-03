import time

import requests

PAGE_SIZE = 100
RATE_LIMIT_SLEEP_SECONDS = 0.25
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


class AirtableClient:
    """Read-only client for the Airtable REST API."""

    def __init__(self, pat: str, base_id: str):
        self._base_url = f"https://api.airtable.com/v0/{base_id}"
        self._headers = {"Authorization": f"Bearer {pat}"}

    def fetch_all_records(self, table_id: str) -> list[dict]:
        records = []
        offset = None

        while True:
            params = {"pageSize": PAGE_SIZE}
            if offset:
                params["offset"] = offset

            data = self._get(table_id, params)
            records.extend(data["records"])

            offset = data.get("offset")
            if not offset:
                break
            time.sleep(RATE_LIMIT_SLEEP_SECONDS)

        return records

    def _get(self, table_id: str, params: dict) -> dict:
        url = f"{self._base_url}/{table_id}"
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, headers=self._headers, params=params, timeout=30)
                if 400 <= response.status_code < 500:
                    # auth/config error (bad PAT, bad base or table id) -- not transient, fail fast
                    response.raise_for_status()
                response.raise_for_status()  # retryable: 5xx
                return response.json()
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                if isinstance(exc, requests.HTTPError) and 400 <= exc.response.status_code < 500:
                    raise
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

        raise RuntimeError(f"Airtable fetch failed after {MAX_RETRIES} attempts") from last_error
