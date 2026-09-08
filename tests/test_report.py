import io
import time
from datetime import date, datetime

import openpyxl
import pandas as pd

from lib.brief import Brief, Insight
from lib.facts import build_fact_pack
from lib.filters import FilterState
from lib.models import DEAL_COLUMNS
from lib.report import build_excel_report, build_pdf_report
from lib.report_data import build_aggregate_tables, build_chart_panels


def _deal_row(i: int, **overrides) -> dict:
    row = {
        "record_id": f"r{i}",
        "originator": "Acme Bio",
        "collaborators": ["Pfizer"],
        "drug": "acme-101",
        "indications_raw": ["Oncology"],
        "indications": ["Oncology"],
        "specific_indication": None,
        "target": None,
        "technologies_raw": ["ADC"],
        "technologies": ["ADC"],
        "phase_raw": None,
        "phase": "Phase 1",
        "maturity": None,
        "asset_type": None,
        "deal_types": ["License"],
        "deal_type_groups": ["License"],
        "deal_type_group": "License",
        "investment_stage": None,
        "upfront_musd": None if i % 5 == 0 else float(10 + i),
        "total_musd": None if i % 7 == 0 else float(100 + i),
        "total_detail": None,
        "based_at": "USA" if i % 2 == 0 else "Europe",
        "deal_date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=i),
        "year": 2020 + i % 5,
        "quarter": 1 + i % 4,
        "source_url": None,
        "related_publications": None,
        "comment": None,
        "needs_review": False,
        "review_notes": None,
        "auto_loaded": True,
        "is_mega_deal": False,
        "has_disclosed_upfront": i % 5 != 0,
        "has_disclosed_total": i % 7 != 0,
    }
    row.update(overrides)
    return row


def _deals_frame(n: int) -> pd.DataFrame:
    if n == 0:
        # Sliced from a populated frame, not pd.DataFrame(columns=...): the
        # latter defaults every column to object dtype, unlike a real 0-row
        # apply_filters() result, which preserves each column's original dtype
        # (bool, float64, ...) -- lib.aggregate's mask/dropna logic depends on
        # that (an object-dtype empty mask silently zeroes out columns).
        return _deals_frame(1).iloc[0:0]
    df = pd.DataFrame([_deal_row(i) for i in range(n)])
    assert set(DEAL_COLUMNS) <= set(df.columns)
    return df


def _extras() -> list[dict]:
    return [{
        "record_id": "extra1",
        "title": "Pfizer expands ADC pipeline",
        "url": "https://example.com/news",
        "why_it_matters": "it matters",
        "category": "readout",
        "date": date(2020, 3, 1),
        "score": 0.83,
        "companies": ["pfizer"],
        "technology_groups": ["adc"],
    }]


def _brief() -> Brief:
    return Brief(
        bullets=["12 deals in view.", "Median deal size $150M."],
        insights=[Insight(text="ADC deals concentrated in the US", news_title=None, news_url=None)],
        news_used=[],
        generated_at=datetime(2026, 1, 1, 12, 0),
    )


def _sheet_rows(wb, name: str) -> list[list]:
    ws = wb[name]
    return [[cell.value for cell in row] for row in ws.iter_rows()]


def _build_context(
    df_filtered: pd.DataFrame,
    df_all: pd.DataFrame | None = None,
    filters: FilterState | None = None,
):
    # df_all mirrors real usage: the whole (never-empty) dataset the filters were
    # applied to, distinct from df_filtered which the empty-result tests narrow
    # to zero rows -- build_fact_pack needs a real year range from df_all even
    # when the filtered view itself is empty.
    df_all = df_filtered if df_all is None else df_all
    filters = filters if filters is not None else FilterState()
    fact_pack = build_fact_pack(df_filtered, df_all, filters)
    agg_tables = build_aggregate_tables(df_filtered, filters)
    panels = build_chart_panels(df_filtered, filters)
    return fact_pack, agg_tables, panels


def test_excel_sheets_and_order():
    df = _deals_frame(20)
    fact_pack, agg_tables, _panels = _build_context(df)
    data = build_excel_report(
        df, fact_pack, _brief(), agg_tables, _extras(), FilterState(), None, datetime(2026, 1, 1),
    )
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Summary", "Deals", "By technology", "By year", "Related news"]


def test_excel_no_related_news_sheet_when_no_matches():
    df = _deals_frame(5)
    fact_pack, agg_tables, _panels = _build_context(df)
    data = build_excel_report(
        df, fact_pack, _brief(), agg_tables, [], FilterState(), None, datetime(2026, 1, 1),
    )
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "Related news" not in wb.sheetnames


def test_excel_deals_sheet_matches_filtered_rows_with_human_columns():
    df = _deals_frame(3)
    fact_pack, agg_tables, _panels = _build_context(df)
    data = build_excel_report(
        df, fact_pack, None, agg_tables, [], FilterState(), None, datetime(2026, 1, 1),
    )
    wb = openpyxl.load_workbook(io.BytesIO(data))
    rows = _sheet_rows(wb, "Deals")
    header, data_rows = rows[0], rows[1:]
    assert "Record ID" in header
    assert "Total value ($M)" in header
    assert len(data_rows) == len(df)  # exactly the filtered rows, no more/no fewer


def test_excel_none_money_is_not_disclosed_never_zero_or_blank():
    df = _deals_frame(10)  # i % 5 == 0 -> upfront None; i % 7 == 0 -> total None
    fact_pack, agg_tables, _panels = _build_context(df)
    data = build_excel_report(
        df, fact_pack, None, agg_tables, [], FilterState(), None, datetime(2026, 1, 1),
    )
    wb = openpyxl.load_workbook(io.BytesIO(data))
    rows = _sheet_rows(wb, "Deals")
    header = rows[0]
    upfront_col = header.index("Upfront ($M)")
    total_col = header.index("Total value ($M)")
    for i, row in enumerate(rows[1:]):
        if i % 5 == 0:
            assert row[upfront_col] == "Not disclosed"
        else:
            assert row[upfront_col] not in (0, None, "")
        if i % 7 == 0:
            assert row[total_col] == "Not disclosed"
        else:
            assert row[total_col] not in (0, None, "")


def test_excel_summary_notes_missing_brief():
    df = _deals_frame(5)
    fact_pack, agg_tables, _panels = _build_context(df)
    data = build_excel_report(
        df, fact_pack, None, agg_tables, [], FilterState(), None, datetime(2026, 1, 1),
    )
    wb = openpyxl.load_workbook(io.BytesIO(data))
    summary_text = "\n".join(str(v) for v, in _sheet_rows(wb, "Summary") if v is not None)
    assert "AI brief not yet generated" in summary_text


def test_excel_empty_filter_result_is_valid_with_headers_only():
    df = _deals_frame(0)
    fact_pack, agg_tables, _panels = _build_context(df, df_all=_deals_frame(5))
    data = build_excel_report(
        df, fact_pack, None, agg_tables, [], FilterState(), None, datetime(2026, 1, 1),
    )
    wb = openpyxl.load_workbook(io.BytesIO(data))
    rows = _sheet_rows(wb, "Deals")
    assert len(rows) == 1  # header row only
    summary_text = "\n".join(str(v) for v, in _sheet_rows(wb, "Summary") if v is not None)
    assert "No deals match the selected filters." in summary_text


def test_pdf_builds_valid_bytes_for_normal_and_empty_view():
    df = _deals_frame(15)
    fact_pack, _agg_tables, panels = _build_context(df)
    data = build_pdf_report(
        df, fact_pack, _brief(), panels, _extras(), FilterState(), None, datetime(2026, 1, 1),
    )
    assert data.startswith(b"%PDF")
    assert len(data) > 1000

    empty_df = _deals_frame(0)
    empty_fact_pack, _agg, empty_panels = _build_context(empty_df, df_all=_deals_frame(5))
    empty_data = build_pdf_report(
        empty_df, empty_fact_pack, None, empty_panels, [], FilterState(), None, datetime(2026, 1, 1),
    )
    assert empty_data.startswith(b"%PDF")


def test_5000_rows_builds_under_15_seconds():
    df = _deals_frame(5000)
    filters = FilterState()
    fact_pack, agg_tables, panels = _build_context(df, filters=filters)

    start = time.time()
    excel_bytes = build_excel_report(
        df, fact_pack, None, agg_tables, [], filters, None, datetime(2026, 1, 1),
    )
    pdf_bytes = build_pdf_report(
        df, fact_pack, None, panels, [], filters, None, datetime(2026, 1, 1),
    )
    elapsed = time.time() - start

    assert len(excel_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF")
    assert elapsed < 15
