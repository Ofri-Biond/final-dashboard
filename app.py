import logging

import streamlit as st

from assets.theme import LOGO_PATH
from assets.theme import register as register_theme
from components.auth import require_auth
from components.brief_card import render_brief
from components.filters_sidebar import render_sidebar
from components.kpis import render_kpis
from components.report_ui import render_report_download
from components.sections import render_raw_data, render_sections
from components.states import empty_state, safe_render
from lib.data import clear_deals_cache, load_deals, reset_caches, sync_now
from lib.filters import (
    FilterState,
    apply_filters,
    data_year_range,
    most_restrictive,
    period_label,
    previous_period,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Biond BD Intelligence Dashboard", layout="wide")

require_auth()

if LOGO_PATH.exists():
    st.logo(str(LOGO_PATH))

st.title("Biond BD Intelligence Dashboard")


def reset_button() -> None:
    """Last-resort recovery: drop every cache (a stale one survives code redeploys)."""
    if st.button("Reset app cache", key="reset_app_cache", icon=":material/restart_alt:"):
        reset_caches()
        st.rerun()


try:
    deals = load_deals()
except Exception as exc:
    logger.exception("Could not load deals")
    st.error(f"Couldn't load the deals data: {exc}")
    if st.button("Retry"):
        sync_now()
        clear_deals_cache()
        st.rerun()
    reset_button()
    st.stop()

try:
    filters = render_sidebar(deals)
except Exception:
    logger.exception("Sidebar failed to render")
    st.sidebar.error("Filters are temporarily unavailable.")
    st.warning("Filters couldn't load, so all deals are shown unfiltered.")
    filters = FilterState()

try:
    register_theme(st.session_state.get("chart_palette", "Default"))
except Exception:
    logger.exception("Could not apply the chart palette; using the default")

try:
    filtered = apply_filters(deals, filters)
except Exception:
    logger.exception("Could not apply filters %s", filters)
    st.error("Couldn't apply the selected filters. Try clearing them, or reset the app cache.")
    reset_button()
    st.stop()

with st.sidebar:
    safe_render("Report download", render_report_download, filtered, deals, filters)

if filtered.empty:
    try:
        culprits = most_restrictive(deals, filters)
    except Exception:
        logger.exception("Could not work out which filter emptied the result")
        culprits = []
    empty_state(culprits)
    st.stop()

# The previous-period comparison is optional -- if it fails, the KPIs render without deltas.
prev_deals, compared_to = None, None
try:
    prev_filters = previous_period(filters, data_year_range(deals))
    if prev_filters is not None:
        prev_deals = apply_filters(deals, prev_filters)
        compared_to = period_label(prev_filters)
except Exception:
    logger.exception("Could not compute the previous-period comparison")
    prev_deals, compared_to = None, None

safe_render("Key metrics", render_kpis, filtered, prev_deals, filters, compared_to)
safe_render("AI market brief", render_brief, filtered, deals, filters)
safe_render("Charts", render_sections, filtered, filters)
safe_render("Raw data preview", render_raw_data, filtered)
