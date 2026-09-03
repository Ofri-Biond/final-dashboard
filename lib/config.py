import os
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    airtable_pat: str
    airtable_base_id: str
    airtable_table_id: str
    cache_dir: Path


def _secret(name: str) -> str:
    """Streamlit Cloud has no .env (the repo is public, .env is gitignored) -- secrets
    there are set via the app's dashboard and only ever reach the process as
    st.secrets. Local dev keeps using .env. st.secrets raises if no secrets.toml
    exists at all, so that path is guarded rather than checked with `in`.
    """
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ[name]


def load_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")

    with open(REPO_ROOT / "config" / "settings.yaml") as f:
        config = yaml.safe_load(f)

    return Settings(
        airtable_pat=_secret("AIRTABLE_PAT"),
        airtable_base_id=_secret("AIRTABLE_BASE_ID"),
        airtable_table_id=config["airtable_table_id"],
        cache_dir=REPO_ROOT / config["cache_dir"],
    )
