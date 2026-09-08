"""The Claude call: turns a fact pack + news context into an executive brief.
Golden rule enforced here, in code, not just in the prompt: every number in the
model's output is checked against the fact pack before it's allowed to render,
and every (news: <title>) citation is checked against the rows actually sent.
Nothing about the deals table itself is ever sent -- only the precomputed pack.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lib.config import REPO_ROOT, _secret

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_CACHE_ENTRIES = 50
BRIEFS_CACHE_FILENAME = "briefs.json"

SYSTEM_PROMPT = (
    "You are a biotech BD analyst writing for executives. Use ONLY the numbers "
    "provided in the fact pack. Never compute, extrapolate, or add figures. The "
    "news items are context: use them to explain WHY a pattern may exist "
    "(approvals, readouts, safety halts, pivots) or to flag a development the "
    "numbers do not show yet; cite each as (news: <title>). Write money exactly "
    "as it appears in the fact pack (e.g. \"$1,234M\") -- never convert to "
    "billions or any other unit. Output JSON: 4-6 'bullets' describing the "
    "current view plainly, then 2-4 'insights': non-obvious patterns an analyst "
    "scanning charts would miss, each citing its numbers and why it matters. "
    "No hype, no advice, no filler."
)

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets": {"type": "array", "items": {"type": "string"}},
        "insights": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["bullets", "insights"],
    "additionalProperties": False,
}

_NUMBER_RE = re.compile(r"[-+]?\$?\d[\d,]*(?:\.\d+)?\s*%?")
_UNIT_SUFFIX_RE = re.compile(r"[-+]?\$?\d[\d,]*(?:\.\d+)?\s*[Bb](?:n|illion)?\b")
_CITATION_RE = re.compile(r"\(news:\s*([^)]+)\)")


class BriefUnavailable(Exception):
    """The brief could not be generated -- missing key, API error, malformed
    response, or every candidate line failed number validation. The UI must
    catch this and fall back to the computed snapshot; never surface it raw.
    """


@dataclass(frozen=True)
class Insight:
    text: str
    news_title: str | None
    news_url: str | None


@dataclass(frozen=True)
class Brief:
    bullets: list[str]
    insights: list[Insight]
    news_used: list[str]
    generated_at: datetime


def is_configured() -> bool:
    try:
        _secret("ANTHROPIC_API_KEY")
        return True
    except KeyError:
        return False


def _canonical_json(fact_pack: dict) -> str:
    return json.dumps(fact_pack, sort_keys=True, separators=(",", ":"))


def brief_key(fact_pack: dict, extras: list[dict]) -> str:
    record_ids = ",".join(sorted(row["record_id"] for row in extras))
    payload = _canonical_json(fact_pack) + "|" + record_ids
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path() -> Path:
    return REPO_ROOT / "data" / "cache" / BRIEFS_CACHE_FILENAME


def _load_cache() -> dict:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Trim to the most recently generated entries so the file can't grow forever.
    trimmed = dict(
        sorted(cache.items(), key=lambda item: item[1]["generated_at"], reverse=True)[
            :MAX_CACHE_ENTRIES
        ]
    )
    path.write_text(json.dumps(trimmed, indent=2))


def _brief_to_payload(brief: Brief) -> dict:
    return {
        "bullets": brief.bullets,
        "insights": [
            {"text": i.text, "news_title": i.news_title, "news_url": i.news_url}
            for i in brief.insights
        ],
        "news_used": brief.news_used,
        "generated_at": brief.generated_at.isoformat(),
    }


def _payload_to_brief(payload: dict) -> Brief:
    return Brief(
        bullets=payload["bullets"],
        insights=[
            Insight(text=i["text"], news_title=i["news_title"], news_url=i["news_url"])
            for i in payload["insights"]
        ],
        news_used=payload["news_used"],
        generated_at=datetime.fromisoformat(payload["generated_at"]),
    )


def load_cached_brief(key: str) -> Brief | None:
    cache = _load_cache()
    payload = cache.get(key)
    return _payload_to_brief(payload) if payload else None


def _collect_allowed_numbers(value, out: set[float]) -> None:
    """Recursively harvest every numeric leaf in the (already-coerced) fact
    pack, plus the length of every list -- so "top 5" or "3 of the 4" are
    legitimate facts about the pack's shape, not invented counts.
    """
    if isinstance(value, dict):
        for v in value.values():
            _collect_allowed_numbers(v, out)
    elif isinstance(value, list):
        out.add(float(len(value)))
        for v in value:
            _collect_allowed_numbers(v, out)
    elif isinstance(value, bool):
        pass
    elif isinstance(value, (int, float)):
        out.add(float(value))


def _candidate_numbers(text: str) -> list[tuple[str, float]]:
    """(raw token, parsed value) pairs for every number-shaped substring, plus
    a rejection marker for money written with a B/billion suffix (the fact
    pack only ever holds $M figures -- unit conversion is invented, not cited).
    """
    candidates = []
    for match in _NUMBER_RE.finditer(text):
        token = match.group()
        if _UNIT_SUFFIX_RE.match(text[match.start():]):
            candidates.append((token, None))  # None = always fails, unit conversion
            continue
        cleaned = token.replace("$", "").replace(",", "").replace("+", "").strip()
        cleaned = cleaned.rstrip("%").strip()
        try:
            value = float(cleaned)
        except ValueError:
            continue
        candidates.append((token, value))
    return candidates


def _decimal_places(token: str) -> int:
    if "." in token:
        return len(token.split(".")[-1].rstrip("%"))
    return 0


def _number_is_allowed(value: float, token: str, allowed: set[float]) -> bool:
    if value is None:
        return False
    # Bare small integers are structural language ("the 2 technologies", "3 of
    # the 4"), not a claim about the data -- allow unconditionally so a correct
    # sentence isn't dropped for using ordinary counting words.
    if "$" not in token and "%" not in token and value == int(value) and 0 <= value <= 10:
        return True
    decimals = _decimal_places(token)
    return any(round(abs(a), decimals) == round(abs(value), decimals) for a in allowed)


def _validate_line(text: str, allowed: set[float]) -> bool:
    for token, value in _candidate_numbers(text):
        if not _number_is_allowed(value, token, allowed):
            logger.warning("Dropping line with unverified number %r: %s", token, text)
            return False
    return True


def _resolve_citation(text: str, news_by_title: dict[str, dict]) -> tuple[str, str | None, str | None]:
    match = _CITATION_RE.search(text)
    if not match:
        return text, None, None
    cited = match.group(1).strip()
    row = news_by_title.get(cited.casefold())
    cleaned_text = (text[: match.start()] + text[match.end():]).strip()
    cleaned_text = re.sub(r"\s{2,}", " ", cleaned_text).strip(" .,;")
    if row is None:
        logger.warning("Dropping unknown news citation %r", cited)
        return cleaned_text, None, None
    return cleaned_text, row["title"], row["url"]


def _call_model(fact_pack: dict, llm_rows: list[dict]) -> dict:
    """The raw API call, isolated so tests can monkeypatch it without network."""
    import anthropic

    client = anthropic.Anthropic(
        api_key=_secret("ANTHROPIC_API_KEY"),
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,  # the SDK retries timeouts by default; that would blow the 20s budget
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": json.dumps({"fact_pack": fact_pack, "news": llm_rows}, indent=2),
        }],
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
        },
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def generate_brief(fact_pack: dict, extras: list[dict]) -> Brief:
    """Call Claude, validate every number and citation against the fact pack /
    sent news rows, cache the result, and return it. Raises BriefUnavailable on
    any failure -- missing key, API error, malformed JSON, or zero surviving
    lines. Never caches a failed attempt.

    Checks the cache first and returns immediately on a hit -- this is what
    guarantees zero API calls for a repeat view even if a caller doesn't check
    load_cached_brief() itself first (the UI does, as the normal path).
    """
    import anthropic

    key = brief_key(fact_pack, extras)
    cached = load_cached_brief(key)
    if cached is not None:
        return cached

    if not is_configured():
        raise BriefUnavailable("ANTHROPIC_API_KEY is not configured")

    llm_rows = [
        {
            "title": row["title"],
            "why_it_matters": row["why_it_matters"][:300],
            "category": row["category"],
            "date": row["date"].isoformat() if row["date"] else None,
            "url": row["url"],
        }
        for row in extras
    ]

    try:
        raw = _call_model(fact_pack, llm_rows)
    except anthropic.AuthenticationError as exc:
        raise BriefUnavailable("invalid Anthropic API key") from exc
    except anthropic.RateLimitError as exc:
        raise BriefUnavailable("Anthropic API rate limited") from exc
    except anthropic.APITimeoutError as exc:
        raise BriefUnavailable("Anthropic API timed out") from exc
    except anthropic.APIConnectionError as exc:
        raise BriefUnavailable("could not reach the Anthropic API") from exc
    except anthropic.APIStatusError as exc:
        raise BriefUnavailable(f"Anthropic API error: {exc}") from exc
    except (json.JSONDecodeError, StopIteration, KeyError) as exc:
        raise BriefUnavailable("malformed response from the model") from exc

    if not isinstance(raw, dict) or "bullets" not in raw or "insights" not in raw:
        raise BriefUnavailable("malformed response shape from the model")

    allowed: set[float] = set()
    _collect_allowed_numbers(fact_pack, allowed)
    news_by_title = {row["title"].casefold(): row for row in llm_rows}

    bullets = [line for line in raw["bullets"] if _validate_line(line, allowed)]

    insights: list[Insight] = []
    news_used: list[str] = []
    for line in raw["insights"]:
        if not _validate_line(line, allowed):
            continue
        text, news_title, news_url = _resolve_citation(line, news_by_title)
        insights.append(Insight(text=text, news_title=news_title, news_url=news_url))
        if news_url:
            news_used.append(news_url)

    if not bullets:
        raise BriefUnavailable("no bullets survived number validation")

    brief = Brief(
        bullets=bullets,
        insights=insights,
        news_used=sorted(set(news_used)),
        generated_at=datetime.now(),
    )

    cache = _load_cache()
    cache[key] = _brief_to_payload(brief)
    _save_cache(cache)

    return brief
