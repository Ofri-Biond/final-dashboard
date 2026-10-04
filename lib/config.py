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
    airtable_extras_table_id: str
    cache_dir: Path


class MissingSecretError(KeyError):
    """A KeyError subclass (callers probing optional secrets catch KeyError) whose
    message says what to do rather than just echoing the key."""

    def __str__(self) -> str:
        return f"Missing secret {self.args[0]} -- set it in the app's Streamlit secrets or .env"


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
    try:
        return os.environ[name]
    except KeyError:
        raise MissingSecretError(name) from None


def _load_config() -> dict:
    with open(REPO_ROOT / "config" / "settings.yaml") as f:
        return yaml.safe_load(f)


def load_cache_dir() -> Path:
    """Where the local cache lives. Needs no secrets, so cache reads (sync state,
    cached data) keep working when the Airtable credentials are missing."""
    return REPO_ROOT / _load_config()["cache_dir"]


def load_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    config = _load_config()

    return Settings(
        airtable_pat=_secret("AIRTABLE_PAT"),
        airtable_base_id=_secret("AIRTABLE_BASE_ID"),
        airtable_table_id=config["airtable_table_id"],
        airtable_extras_table_id=config["airtable_extras_table_id"],
        cache_dir=REPO_ROOT / config["cache_dir"],
    )
