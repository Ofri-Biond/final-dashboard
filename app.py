import streamlit as st

from assets.theme import LOGO_PATH
from assets.theme import register as register_theme
from components.auth import require_auth
from components.filters_sidebar import render_sidebar
from components.kpis import render_kpis
from components.sections import render_raw_data, render_sections
from components.states import empty_state
from lib.data import load_deals
from lib.filters import apply_filters, most_restrictive, previous_period

st.set_page_config(page_title="Biond BD Intelligence Dashboard", layout="wide")
register_theme()

require_auth()

if LOGO_PATH.exists():
    st.logo(str(LOGO_PATH))

st.title("Biond BD Intelligence Dashboard")

deals = load_deals()
filters = render_sidebar(deals)
filtered = apply_filters(deals, filters)

if filtered.empty:
    empty_state(most_restrictive(deals, filters))
    st.stop()

data_years = (int(deals["year"].min()), int(deals["year"].max()))
prev_filters = previous_period(filters, data_years)
prev_deals = apply_filters(deals, prev_filters) if prev_filters is not None else None

render_kpis(filtered, prev_deals, filters)
render_sections(filtered, filters)
render_raw_data(filtered)
