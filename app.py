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
from lib.data import load_deals, sync_now
from lib.filters import (
    apply_filters,
    data_year_range,
    most_restrictive,
    previous_period,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Biond BD Intelligence Dashboard", layout="wide")

require_auth()

if LOGO_PATH.exists():
    st.logo(str(LOGO_PATH))

st.title("Biond BD Intelligence Dashboard")

try:
    deals = load_deals()
except Exception as exc:
    logger.exception("Could not load deals")
    st.error(f"Couldn't load the deals data: {exc}")
    if st.button("Retry"):
        sync_now()
        load_deals.clear()
        st.rerun()
    st.stop()

filters = render_sidebar(deals)
register_theme(st.session_state.get("chart_palette", "Default"))
filtered = apply_filters(deals, filters)

with st.sidebar:
    safe_render("Report download", render_report_download, filtered, deals, filters)

if filtered.empty:
    empty_state(most_restrictive(deals, filters))
    st.stop()

prev_filters = previous_period(filters, data_year_range(deals))
prev_deals = apply_filters(deals, prev_filters) if prev_filters is not None else None

safe_render("Key metrics", render_kpis, filtered, prev_deals, filters)
safe_render("AI market brief", render_brief, filtered, deals, filters)
render_sections(filtered, filters)
safe_render("Raw data preview", render_raw_data, filtered)
