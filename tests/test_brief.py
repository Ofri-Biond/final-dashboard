import datetime
import json

import pytest

import lib.brief as brief_module
from lib.brief import BriefUnavailable, brief_key, generate_brief, load_cached_brief


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Every test gets its own briefs.json -- never touch the real repo cache."""
    cache_file = tmp_path / "briefs.json"
    monkeypatch.setattr(brief_module, "_cache_path", lambda: cache_file)
    monkeypatch.setattr(brief_module, "is_configured", lambda: True)
    return cache_file


def _fact_pack() -> dict:
    return {
        "snapshot": {"deal_count": 694, "median_total_musd": 369.0},
        "trends": {"top_technologies_by_count": {"rows": [{"name": "ADC"}, {"name": "CAR"}]}},
    }


def _extras() -> list[dict]:
    # Matches lib.extras.get_extras_context's real row shape -- "date" is a
    # datetime.date object, not a string (regression: generate_brief passed
    # this straight into json.dumps() for the API request, which raises on a
    # bare date; see test_llm_payload_date_is_json_serializable below).
    return [{
        "record_id": "extra1",
        "title": "known news item",
        "url": "https://example.com/news",
        "why_it_matters": "it matters",
        "category": "readout",
        "date": datetime.date(2026, 8, 1),
        "score": 0.7,
    }]


def _stub_model(bullets, insights):
    def _call(fact_pack, llm_rows):
        return {"bullets": bullets, "insights": insights}
    return _call


def test_bullet_with_invented_number_is_dropped(monkeypatch):
    monkeypatch.setattr(
        brief_module, "_call_model",
        _stub_model(["694 deals in view.", "Deal count doubled to 1240 from 620."], []),
    )
    result = generate_brief(_fact_pack(), _extras())
    assert result.bullets == ["694 deals in view."]


def test_formatting_tolerant_number_variants_are_kept(monkeypatch):
    monkeypatch.setattr(
        brief_module, "_call_model",
        _stub_model(["Median deal size is $369M.", "Median deal size is $369.0M exactly."], []),
    )
    result = generate_brief(_fact_pack(), _extras())
    assert len(result.bullets) == 2


def test_a_list_length_counts_as_an_allowed_number(monkeypatch):
    monkeypatch.setattr(
        brief_module, "_call_model",
        _stub_model(["The top 2 technologies dominate."], []),
    )
    result = generate_brief(_fact_pack(), _extras())
    assert result.bullets == ["The top 2 technologies dominate."]


def test_bare_small_integer_passes_but_dollar_prefixed_does_not(monkeypatch):
    monkeypatch.setattr(
        brief_module, "_call_model",
        _stub_model(["3 of the 2 technologies are new.", "Deal size grew by $3."], []),
    )
    result = generate_brief(_fact_pack(), _extras())
    assert result.bullets == ["3 of the 2 technologies are new."]


def test_billion_denominated_money_is_rejected(monkeypatch):
    monkeypatch.setattr(
        brief_module, "_call_model",
        _stub_model(["694 deals in view.", "Total value reached $0.694B."], []),
    )
    result = generate_brief(_fact_pack(), _extras())
    assert result.bullets == ["694 deals in view."]


def test_known_news_citation_resolves_to_its_url(monkeypatch):
    monkeypatch.setattr(
        brief_module, "_call_model",
        _stub_model(
            ["694 deals in view."],
            ["Something notable happened (news: known news item)."],
        ),
    )
    result = generate_brief(_fact_pack(), _extras())
    assert len(result.insights) == 1
    assert result.insights[0].news_title == "known news item"
    assert result.insights[0].news_url == "https://example.com/news"
    assert "(news:" not in result.insights[0].text
    assert result.news_used == ["https://example.com/news"]


def test_unknown_news_citation_is_stripped_but_sentence_kept(monkeypatch):
    monkeypatch.setattr(
        brief_module, "_call_model",
        _stub_model(
            ["694 deals in view."],
            ["Something notable happened (news: a title never sent)."],
        ),
    )
    result = generate_brief(_fact_pack(), _extras())
    assert len(result.insights) == 1
    assert result.insights[0].news_url is None
    assert "(news:" not in result.insights[0].text
    assert result.news_used == []


def test_zero_surviving_bullets_raises_brief_unavailable(monkeypatch):
    monkeypatch.setattr(
        brief_module, "_call_model",
        _stub_model(["Deal count doubled to 1240 from 620."], []),
    )
    with pytest.raises(BriefUnavailable):
        generate_brief(_fact_pack(), _extras())


def test_failed_generation_caches_nothing(monkeypatch, _isolated_cache):
    monkeypatch.setattr(
        brief_module, "_call_model",
        _stub_model(["Deal count doubled to 1240 from 620."], []),
    )
    with pytest.raises(BriefUnavailable):
        generate_brief(_fact_pack(), _extras())
    assert not _isolated_cache.exists()


def test_cache_round_trips_and_a_repeat_call_makes_no_api_call(monkeypatch):
    calls = {"count": 0}

    def _call(fact_pack, llm_rows):
        calls["count"] += 1
        return {"bullets": ["694 deals in view."], "insights": []}

    monkeypatch.setattr(brief_module, "_call_model", _call)

    fact_pack, extras = _fact_pack(), _extras()
    first = generate_brief(fact_pack, extras)
    second = generate_brief(fact_pack, extras)

    assert calls["count"] == 1
    assert first.bullets == second.bullets

    cached = load_cached_brief(brief_key(fact_pack, extras))
    assert cached is not None
    assert cached.bullets == ["694 deals in view."]


def test_llm_payload_date_is_json_serializable(monkeypatch):
    """Regression: extras rows carry a real datetime.date (lib.extras' actual
    output shape); the payload built for the API request must convert it to a
    string before generate_brief hands it to _call_model, or the real
    _call_model's json.dumps(...) raises TypeError: Object of type date is not
    JSON serializable.
    """
    received = {}

    def _call(fact_pack, llm_rows):
        received["llm_rows"] = llm_rows
        return {"bullets": ["694 deals in view."], "insights": []}

    monkeypatch.setattr(brief_module, "_call_model", _call)
    generate_brief(_fact_pack(), _extras())

    assert received["llm_rows"][0]["date"] == "2026-08-01"
    json.dumps({"fact_pack": _fact_pack(), "news": received["llm_rows"]})  # must not raise
