import pandas as pd
import pytest

from components import filters_sidebar
from lib import data
from lib.dictionaries import Dictionary
from lib.models import DEAL_COLUMNS


class _OldDictionary:
    """Stands in for an instance of the pre-reload Dictionary class, as cache_resource
    keeps serving after a redeploy -- no `categories` attribute."""


class _FakeCached:
    def __init__(self, *results):
        self._results = list(results)
        self.cleared = 0

    def __call__(self):
        return self._results[min(self.cleared, len(self._results) - 1)]

    def clear(self):
        self.cleared += 1


def test_stale_cached_dictionaries_are_reloaded(monkeypatch):
    fresh = {"technology": Dictionary("technology", {"CAR therapy": ["CAR T cells"]})}
    fake = _FakeCached({"technology": _OldDictionary()}, fresh)
    monkeypatch.setattr(data, "_load_dictionaries_cached", fake)

    assert data._dictionaries() is fresh
    assert fake.cleared == 1
    assert data.dictionary_categories("technology") == frozenset({"CAR therapy"})


def test_dictionary_categories_never_raises(monkeypatch):
    monkeypatch.setattr(data, "_load_dictionaries_cached", _FakeCached({}))
    assert data.dictionary_categories("no_such_dictionary") == frozenset()


def test_stale_deals_frame_is_rebuilt(monkeypatch):
    fresh = pd.DataFrame(columns=DEAL_COLUMNS)
    fake = _FakeCached(pd.DataFrame(columns=["deal_id"]), fresh)
    monkeypatch.setattr(data, "_load_deals_cached", fake)

    assert data.load_deals() is fresh
    assert fake.cleared == 1


def test_deals_still_missing_columns_raises_data_error(monkeypatch):
    monkeypatch.setattr(data, "_load_deals_cached", _FakeCached(pd.DataFrame(columns=["deal_id"])))
    with pytest.raises(data.DataError, match="missing expected columns"):
        data.load_deals()


def test_filter_options_degrade_to_empty_on_missing_column():
    df = pd.DataFrame({"year": [2025]})
    assert filters_sidebar._list_options(df, "technologies") == []
    assert filters_sidebar._phase_options(df) == []
    assert filters_sidebar._unique_options(df, "based_at") == []
    assert filters_sidebar._year_options(df) == [2025]
