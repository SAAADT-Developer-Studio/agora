"""Story title step.

The headline is stored on ``story.title``. ``title_source`` records whether that
text is the first article's title (``article``) or an LLM headline (``generated``).
``title_generated_at`` and ``title_lead_article_id`` remember the last successful
generation so a later article does not call the model again.

A later summary or bullets step can follow the same shape: load
``ArticleExcerpt`` rows, decide whether the article set changed enough, call
OpenRouter, and keep the previous text when the call fails.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

MODEL = "deepseek/deepseek-v4-flash"
_TIMEOUT_SECONDS = 30
# Enough for a short JSON headline. Caps a rambling completion.
_MAX_TOKENS = 200

TITLE_SOURCE_ARTICLE = "article"
TITLE_SOURCE_GENERATED = "generated"
# Membership is added one article at a time, so landing on one of these counts
# means the story just crossed that size. Past the last threshold, only a new
# lead article refreshes the headline.
TITLE_COUNT_THRESHOLDS = frozenset({3, 5, 10, 20, 40})
PROMPT_ARTICLE_LIMIT = 6
_EXCERPT_CHARS = 400
_MIN_TITLE_CHARS = 8
_MAX_TITLE_CHARS = 120

logger = logging.getLogger(__name__)
_missing_key_logged = False

_TITLE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "story_title",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        },
    },
}

_JUNK_PREFIXES = ("here is", "here's", "headline:", "title:", "naslov:", "naslov je")


class _MissingKey(Exception):
    pass


@dataclass(frozen=True)
class ArticleExcerpt:
    article_id: int
    title: str
    deck: str | None
    summary: str | None
    published_at: datetime


def ordered_excerpts(excerpts: Sequence[ArticleExcerpt]) -> list[ArticleExcerpt]:
    return sorted(excerpts, key=lambda item: (item.published_at, item.article_id))


def lead_article(excerpts: Sequence[ArticleExcerpt]) -> ArticleExcerpt | None:
    """Earliest published article. Its title is the fallback headline."""
    ordered = ordered_excerpts(excerpts)
    return ordered[0] if ordered else None


def prompt_excerpts(
    excerpts: Sequence[ArticleExcerpt], limit: int = PROMPT_ARTICLE_LIMIT
) -> list[ArticleExcerpt]:
    """Lead article, then the most recent others.

    Shared selection for this headline and a later summary prompt.
    """
    ordered = ordered_excerpts(excerpts)
    if not ordered or limit < 1:
        return []
    lead = ordered[0]
    rest = ordered[1:]
    if len(rest) > limit - 1:
        keep = {item.article_id for item in rest[-(limit - 1) :]}
        rest = [item for item in rest if item.article_id in keep]
    return [lead, *rest]


def should_generate_title(
    *,
    title_source: str | None,
    stored_lead_article_id: int | None,
    member_count: int,
    lead_article_id: int,
    is_new: bool,
) -> bool:
    if is_new or title_source != TITLE_SOURCE_GENERATED:
        return True
    if lead_article_id != stored_lead_article_id:
        return True
    return member_count in TITLE_COUNT_THRESHOLDS


def build_title_prompt(excerpts: Sequence[ArticleExcerpt]) -> str:
    chosen = prompt_excerpts(excerpts)
    if not chosen:
        return ""
    lines = [
        "You write headlines for a Slovenian news story.",
        "",
        "Write one headline from the articles below.",
        "Use the language of the articles (Slovenian, when the articles are Slovenian).",
        "Be neutral, factual, and concise. Stay under 100 characters.",
        "Use natural capitalization: capitalize the first letter and proper names only.",
        "No clickbait, no questions, no exclamation marks, and no outlet or website names.",
        "",
        "Articles:",
    ]
    for index, excerpt in enumerate(chosen, start=1):
        lines.append(f"{index}. Title: {_clip(excerpt.title, limit=300) or excerpt.title}")
        lead = _clip(excerpt.deck)
        summary = _clip(excerpt.summary)
        if lead:
            lines.append(f"   Lead: {lead}")
        if summary:
            lines.append(f"   Summary: {summary}")
    return "\n".join(lines)


def parse_title(content: str) -> str | None:
    candidate = content.strip()
    if candidate[:1] in "{[":
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        title = data.get("title")
        if not isinstance(title, str):
            return None
        candidate = title
    candidate = " ".join(candidate.split())
    if len(candidate) >= 2 and (
        (candidate[0] == '"' and candidate[-1] == '"')
        or (candidate[0] == "'" and candidate[-1] == "'")
        or (candidate[0] == "«" and candidate[-1] == "»")
    ):
        candidate = candidate[1:-1].strip()
    if not _is_usable_title(candidate):
        return None
    return candidate


def generate_title(
    excerpts: Sequence[ArticleExcerpt],
    *,
    complete: Callable[[str], str] | None = None,
) -> str | None:
    """Return a headline, or None when the model is unavailable or unusable."""
    prompt = build_title_prompt(excerpts)
    if not prompt:
        return None
    call = complete if complete is not None else _complete
    try:
        raw = call(prompt)
    except _MissingKey:
        return None
    except Exception:
        logger.warning("Story title generation failed", exc_info=True)
        return None
    if not isinstance(raw, str):
        logger.warning("Story title generation returned %s", type(raw).__name__)
        return None
    title = parse_title(raw)
    if title is None:
        logger.warning("Story title generation returned unusable text: %r", raw[:180])
    return title


def refresh_story_title(
    story: object,
    excerpts: Sequence[ArticleExcerpt],
    *,
    is_new: bool,
    complete: Callable[[str], str] | None = None,
    now: datetime | None = None,
) -> None:
    """Set ``story.title`` from the model, or leave the first-article title."""
    lead = lead_article(excerpts)
    if lead is None:
        return
    if not should_generate_title(
        title_source=getattr(story, "title_source"),
        stored_lead_article_id=getattr(story, "title_lead_article_id"),
        member_count=len(excerpts),
        lead_article_id=lead.article_id,
        is_new=is_new,
    ):
        return
    generated = generate_title(excerpts, complete=complete)
    if generated is None:
        if getattr(story, "title_source") != TITLE_SOURCE_GENERATED:
            story.title = lead.title
            story.title_source = TITLE_SOURCE_ARTICLE
        return
    story.title = generated
    story.title_source = TITLE_SOURCE_GENERATED
    story.title_generated_at = now if now is not None else datetime.now(timezone.utc)
    story.title_lead_article_id = lead.article_id
    logger.info("Story %s title: %s", getattr(story, "id", None), generated)


def _clip(text: str | None, limit: int = _EXCERPT_CHARS) -> str | None:
    if text is None:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _is_usable_title(text: str) -> bool:
    if not _MIN_TITLE_CHARS <= len(text) <= _MAX_TITLE_CHARS:
        return False
    if any(char in text for char in "!?"):
        return False
    if text[0] in "#*-`>":
        return False
    lowered = text.casefold()
    if lowered.startswith(_JUNK_PREFIXES):
        return False
    if "http://" in lowered or "https://" in lowered or "www." in lowered:
        return False
    return True


def _complete(prompt: str) -> str:
    global _missing_key_logged
    primary = os.getenv("OPENROUTER_API_KEY") or None
    if not primary:
        if not _missing_key_logged:
            logger.warning("OPENROUTER_API_KEY missing; story titles stay on the first article")
            _missing_key_logged = True
        raise _MissingKey()
    try:
        return _post(primary, prompt)
    except urllib.error.HTTPError as exc:
        fallback = os.getenv("OPENROUTER_FALLBACK_API_KEY") or os.getenv(
            "OPENROUTER_API_KEY_FALLBACK"
        )
        if exc.code == 402 and fallback:
            return _post(fallback, prompt)
        raise


def _post(api_key: str, prompt: str) -> str:
    url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "reasoning": {"enabled": False},
        "max_tokens": _MAX_TOKENS,
        "response_format": _TITLE_RESPONSE_FORMAT,
    }
    request = urllib.request.Request(
        f"{url}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read())
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError(f"expected string content, got {content!r}")
    return content
