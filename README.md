# Biond BD Intelligence Dashboard

## Setup

1. Create a virtualenv and install dependencies:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Confirm `.env` has `AIRTABLE_PAT` and `AIRTABLE_BASE_ID` set. `ANTHROPIC_API_KEY` is
   optional -- it powers the AI Market Brief card; without it, that card falls back to a
   computed summary instead of an AI-written brief.
3. Pull the Airtable data into the local cache:
   ```
   python scripts/sync.py
   ```
4. Set the dashboard password:
   ```
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```
   then edit `.streamlit/secrets.toml` and set `APP_PASSWORD`.
5. Run the app:
   ```
   streamlit run app.py
   ```
