"""Password gate. Call require_auth() first thing in app.py -- it st.stop()s
until authenticated, so nothing else in the page (sidebar included) renders.
"""

import streamlit as st

from assets.theme import LOGO_PATH


def _app_password() -> str | None:
    try:
        return st.secrets.get("APP_PASSWORD")
    except Exception:
        return None


def require_auth() -> None:
    if st.session_state.get("authenticated"):
        return

    password = _app_password()
    if password is None:
        st.error(
            "No `APP_PASSWORD` configured. Copy `.streamlit/secrets.toml.example` to "
            "`.streamlit/secrets.toml` and set it."
        )
        st.stop()

    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        with st.container(border=True):
            if LOGO_PATH.exists():
                st.image(str(LOGO_PATH), width=166)
            else:
                st.markdown(
                    "<h1 style='color:#2E86A0;margin-bottom:0;'>BIOND</h1>",
                    unsafe_allow_html=True,
                )
            st.caption("BD Intelligence Dashboard")

            with st.form("login", border=False):
                entered = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Enter", width="stretch")

            if submitted:
                if entered == password:
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Incorrect password")

    st.stop()
