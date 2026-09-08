"""Downloadable report builders: the current filtered view as an .xlsx workbook
or a .pdf brief, built from exactly the same objects the dashboard renders
(fact pack, cached Brief, ChartPanel list) so a report can never show numbers
that disagree with the screen it was downloaded from. Pure -- no `streamlit`.
"""

import io
import tempfile
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import plotly.io as pio
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image as RLImage,
)
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from assets.theme import TEAL
from lib.brief import Brief
from lib.export import to_excel_bytes
from lib.facts import snapshot_lines
from lib.filters import FilterState, describe
from lib.models import Deal
from lib.report_data import ChartPanel

# ---------------------------------------------------------------------------
# Shared formatting helpers
# ---------------------------------------------------------------------------

_MONEY_COLUMNS = ("upfront_musd", "total_musd")
_LIST_COLUMN_JOIN = ", "

DEAL_COLUMN_LABELS: dict[str, str] = {
    "record_id": "Record ID",
    "originator": "Originator",
    "collaborators": "Collaborators",
    "drug": "Drug",
    "indications_raw": "Indication (raw)",
    "indications": "Indication",
    "specific_indication": "Specific indication",
    "target": "Target",
    "technologies_raw": "Technology (raw)",
    "technologies": "Technology",
    "phase_raw": "Phase (raw)",
    "phase": "Phase",
    "maturity": "Maturity",
    "asset_type": "Asset type",
    "deal_types": "Deal type (raw)",
    "deal_type_groups": "Deal type groups",
    "deal_type_group": "Deal type group",
    "investment_stage": "Investment stage",
    "upfront_musd": "Upfront ($M)",
    "total_musd": "Total value ($M)",
    "total_detail": "Total value detail",
    "based_at": "Based at",
    "deal_date": "Deal date",
    "year": "Year",
    "quarter": "Quarter",
    "source_url": "Source URL",
    "related_publications": "Related publications",
    "comment": "Comment",
    "needs_review": "Needs review",
    "review_notes": "Review notes",
    "auto_loaded": "Auto-loaded",
    "is_mega_deal": "Mega deal",
    "has_disclosed_upfront": "Upfront disclosed",
    "has_disclosed_total": "Total disclosed",
}
assert set(DEAL_COLUMN_LABELS) == {f.name for f in fields(Deal)}


def _money(value: float | None) -> str:
    # pd.isna, not `value is None`: a money column read out of a DataFrame carries
    # missing values as float NaN, not Python None -- `value is None` would let
    # "$nanM" through.
    return "Not disclosed" if pd.isna(value) else f"${value:,.0f}M"


def _freshness_line(sync_state) -> str:
    if sync_state is None:
        return "Data freshness: no data cached yet."
    if sync_state.status == "failed":
        return f"Data freshness: last sync failed ({sync_state.error_message}); showing last good data."
    return f"Data freshness: data as of {sync_state.last_sync_at:%Y-%m-%d %H:%M}."


def _brief_lines(fact_pack: dict, brief: Brief | None) -> list[str]:
    """The AI brief's bullets/insights as plain text, or -- when no brief has
    been generated for this exact view yet -- the same computed-snapshot
    fallback the dashboard itself falls back to (lib.facts.snapshot_lines).
    """
    if brief is not None:
        lines = ["AI Market Brief:"] + [f"- {b}" for b in brief.bullets]
        if brief.insights:
            lines.append("What you might have missed:")
            for insight in brief.insights:
                text = insight.text
                if insight.news_url:
                    text = f"{text} ({insight.news_title})"
                lines.append(f"- {text}")
        return lines

    lines = ["AI brief not yet generated for this view -- showing computed summary:"]
    lines += [f"- {line}" for line in snapshot_lines(fact_pack)]
    return lines


def _kpi_lines(fact_pack: dict) -> list[str]:
    kpis = fact_pack["kpis"]["current"]
    return [
        f"Deals: {kpis['deal_count']:,.0f}",
        f"Total disclosed value: {_money(kpis['disclosed_total_value_musd'])}",
        f"Median deal size: {_money(kpis['median_total_musd'])}",
        f"Median upfront: {_money(kpis['median_upfront_musd'])}",
    ]


def _meta_lines(filters: FilterState, sync_state, generated_at: datetime) -> list[str]:
    return [
        f"Generated: {generated_at:%Y-%m-%d %H:%M}",
        f"Filters: {describe(filters)}",
        _freshness_line(sync_state),
    ]


def _deals_sheet(df_filtered: pd.DataFrame) -> pd.DataFrame:
    """The exact rows/columns of the "Raw data preview" table, money formatted
    as "Not disclosed"/"$X,XXXM" text (never 0/blank) and list columns joined
    to comma-separated text -- Excel cells can't hold a Python list, so this is
    the closest lossless equivalent of what the app shows as a Python list.
    """
    display = df_filtered.copy()
    for col in _MONEY_COLUMNS:
        if col in display.columns:
            display[col] = df_filtered[col].apply(_money)
    for col in display.columns:
        if display[col].dtype != object:
            continue  # only an object-dtype column could hold a Python list
        if display[col].apply(lambda v: isinstance(v, (list, tuple))).any():
            display[col] = display[col].apply(
                lambda v: _LIST_COLUMN_JOIN.join(str(x) for x in v) if isinstance(v, (list, tuple)) else v
            )
    return display.rename(columns=DEAL_COLUMN_LABELS)


def _extras_sheet(extras: list[dict]) -> pd.DataFrame:
    rows = [
        {
            "Date": row["date"].isoformat() if row["date"] else None,
            "Title": row["title"],
            "URL": row["url"],
            "Category": row["category"],
            "Score": row["score"],
        }
        for row in extras
    ]
    return pd.DataFrame(rows, columns=["Date", "Title", "URL", "Category", "Score"])


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------


def build_excel_report(
    df_filtered: pd.DataFrame,
    fact_pack: dict,
    brief: Brief | None,
    agg_tables: dict[str, pd.DataFrame],
    extras: list[dict],
    filters: FilterState,
    sync_state,
    generated_at: datetime,
) -> bytes:
    if df_filtered.empty:
        summary_lines = ["No deals match the selected filters."] + _meta_lines(
            filters, sync_state, generated_at
        )
    else:
        summary_lines = (
            ["KPIs:"]
            + [f"- {line}" for line in _kpi_lines(fact_pack)]
            + [""]
            + _brief_lines(fact_pack, brief)
            + [""]
            + _meta_lines(filters, sync_state, generated_at)
        )

    sheets: dict[str, pd.DataFrame] = {
        "Summary": pd.DataFrame({"Summary": summary_lines}),
        "Deals": _deals_sheet(df_filtered),
        "By technology": agg_tables["By technology"],
        "By year": agg_tables["By year"],
    }
    if extras:
        sheets["Related news"] = _extras_sheet(extras)

    return to_excel_bytes(sheets)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

_STYLES = getSampleStyleSheet()
_BODY = ParagraphStyle("BiondBody", parent=_STYLES["Normal"], fontSize=9, leading=12)
_ITALIC = ParagraphStyle("BiondItalic", parent=_STYLES["Italic"], fontSize=8, textColor=colors.grey)
_HEADING = ParagraphStyle(
    "BiondHeading", parent=_STYLES["Heading2"], textColor=colors.HexColor(TEAL), spaceBefore=10
)
_TABLE_HEADER_STYLE = ParagraphStyle("BiondTableHeader", parent=_BODY, textColor=colors.white)
_PAGE_WIDTH, _ = letter
_CONTENT_WIDTH = _PAGE_WIDTH - 1.5 * inch
_CHART_EXPORT_SIZE = (1000, 550)  # px, kaleido export -- fixed aspect for every panel


def _p(text: str, style: ParagraphStyle = _BODY) -> Paragraph:
    return Paragraph(escape(text), style)


def _batch_chart_images(panels: list[ChartPanel]) -> dict[str, bytes]:
    """PNG bytes for every panel's figure, rendered in one kaleido batch call.
    Exporting each figure with its own to_image() call pays kaleido's ~1.5-2s
    per-call startup cost every time (9 panels -> 15s+, blowing the report's
    own <10s target); plotly.io.write_images renders the whole batch in one
    browser session instead (~2.5s total regardless of panel count). It only
    writes to real file paths (a BytesIO target silently receives nothing), so
    a scratch temp dir is used and immediately cleaned up.
    """
    if not panels:
        return {}
    width, height = _CHART_EXPORT_SIZE
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"{panel.key}.png" for panel in panels]
        pio.write_images(
            [panel.figure for panel in panels],
            [str(p) for p in paths],
            format="png", width=width, height=height, scale=2,
        )
        return {panel.key: path.read_bytes() for panel, path in zip(panels, paths, strict=True)}


def _chart_image(png_bytes: bytes) -> RLImage:
    width, height = _CHART_EXPORT_SIZE
    display_width = _CONTENT_WIDTH
    display_height = display_width * height / width
    return RLImage(io.BytesIO(png_bytes), width=display_width, height=display_height)


def _extras_table(extras: list[dict]) -> Table:
    header = [_p("Date", _TABLE_HEADER_STYLE), _p("Title", _TABLE_HEADER_STYLE),
              _p("Category", _TABLE_HEADER_STYLE), _p("Score", _TABLE_HEADER_STYLE)]
    rows = [header]
    for row in extras:
        date_text = row["date"].isoformat() if row["date"] else "undated"
        title = row["title"] or row["url"] or "untitled"
        title_text = f'<link href="{escape(row["url"])}">{escape(title)}</link>' if row["url"] else escape(title)
        rows.append([
            _p(date_text), Paragraph(title_text, _BODY), _p(row["category"]), _p(f"{row['score']:.2f}"),
        ])
    table = Table(rows, colWidths=[0.8 * inch, _CONTENT_WIDTH - 2.4 * inch, 1.0 * inch, 0.6 * inch], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(TEAL)),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E8EDEF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def build_pdf_report(
    df_filtered: pd.DataFrame,
    fact_pack: dict,
    brief: Brief | None,
    panels: list[ChartPanel],
    extras: list[dict],
    filters: FilterState,
    sync_state,
    generated_at: datetime,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    story: list = [
        Paragraph("Biond BD Intelligence Dashboard", _STYLES["Title"]),
        _p(f"Report generated {generated_at:%Y-%m-%d %H:%M} — {describe(filters)}"),
        _p(_freshness_line(sync_state)),
        Spacer(1, 0.15 * inch),
    ]

    if df_filtered.empty:
        story.append(_p("No deals match the selected filters."))
        doc.build(story)
        return buffer.getvalue()

    story.append(Paragraph("AI Market Brief", _HEADING))
    for line in _brief_lines(fact_pack, brief):
        story.append(_p(line))
    story.append(Spacer(1, 0.1 * inch))

    images = _batch_chart_images(panels)
    for panel in panels:
        story.append(Paragraph(escape(panel.title), _HEADING))
        story.append(_p(panel.finding))
        story.append(_chart_image(images[panel.key]))
        if panel.coverage is not None:
            story.append(_p(panel.coverage.note(), _ITALIC))
        story.append(Spacer(1, 0.1 * inch))

    if extras:
        story.append(Paragraph(f"Related news ({len(extras)})", _HEADING))
        story.append(_extras_table(extras))

    doc.build(story)
    return buffer.getvalue()
