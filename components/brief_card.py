"""The AI Market Brief card: a cached brief renders instantly (zero API calls);
otherwise a button lets the user spend one call on the current view. Every
number shown comes from lib.facts; the LLM (lib.brief) only turns those numbers
into prose, validated against the pack before it renders. On any failure --
missing API key, a bad response, a timeout -- the card falls back to the
Python-formatted fact-pack snapshot. Never an error.
"""

import logging

import pandas as pd
import streamlit as st

from lib.brief import (
    Brief,
    BriefUnavailable,
    brief_key,
    generate_brief,
    is_configured,
    load_cached_brief,
)
from lib.extras import get_extras_context
from lib.facts import build_fact_pack, snapshot_lines
from lib.filters import FilterState, describe

logger = logging.getLogger(__name__)


def _render_related_news(extras: list[dict]) -> None:
    if not extras:
        return
    with st.expander(f"Related news ({len(extras)})", icon=":material/newspaper:"):
        for row in extras:
            date_text = row["date"].isoformat() if row["date"] else "undated"
            title = row["title"] or row["url"] or "untitled"
            link = f"[{title}]({row['url']})" if row["url"] else title
            st.markdown(
                f"{date_text} — {link} &nbsp;:gray-badge[{row['category']}] "
                f"&nbsp;score {row['score']:.2f}"
            )


def _render_footer(filters: FilterState, generated_at) -> None:
    st.caption(
        f"AI-generated from the numbers above. Generated {generated_at:%H:%M}, "
        f"filters: {describe(filters)}"
    )


def _render_brief(brief: Brief, extras: list[dict], filters: FilterState) -> None:
    for bullet in brief.bullets:
        st.markdown(f"- {bullet}")

    if brief.insights:
        st.markdown("**What you might have missed**")
        for insight in brief.insights:
            text = insight.text
            if insight.news_url:
                text = f"{text} ([{insight.news_title}]({insight.news_url}))"
            st.markdown(f":orange-badge[Missed] {text}")

    _render_related_news(extras)
    _render_footer(filters, brief.generated_at)


def _render_unavailable(fact_pack: dict, extras: list[dict]) -> None:
    for line in snapshot_lines(fact_pack):
        st.markdown(f"- {line}")
    _render_related_news(extras)
    st.caption("AI unavailable, showing computed summary")


def render_brief(df_filtered: pd.DataFrame, df_all: pd.DataFrame, filters: FilterState) -> None:
    with st.container(border=True):
        st.subheader(":material/auto_awesome: AI Market Brief")

        extras = get_extras_context(df_filtered, filters)
        fact_pack = build_fact_pack(df_filtered, df_all, filters)
        key = brief_key(fact_pack, extras)
        cached = load_cached_brief(key)

        if cached is not None:
            _render_brief(cached, extras, filters)
            return

        if not is_configured():
            _render_unavailable(fact_pack, extras)
            return

        st.caption("No brief generated yet for this view.")
        if st.button("Generate brief for current view", key="brief_generate"):
            with st.spinner("Reading the data..."):
                try:
                    generate_brief(fact_pack, extras)
                except BriefUnavailable as exc:
                    # generate_brief caches nothing on failure, so the fallback
                    # renders in place here rather than rerunning into the same
                    # "no brief yet" state with no explanation of what happened.
                    logger.warning("Brief generation failed: %s", exc)
                    _render_unavailable(fact_pack, extras)
                    return
            st.rerun()  # re-enter this function so the now-cached brief renders
