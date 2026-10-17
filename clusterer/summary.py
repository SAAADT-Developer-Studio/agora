"""Story summary step: one LLM call for a headline plus key-point bullets.

Each refresh writes a new ``story_summary`` row and copies its title onto
``story.title``. Until the first one succeeds, ``story.title`` stays the
earliest article's title.

Token use is bounded no matter how big the story gets: the prompt holds the
earliest article, the five most recent, and the previous bullets. The previous
bullets carry what older articles said, so the model keeps what still holds and
changes only what the new articles update. That also keeps the wording stable
between refreshes.

Later: a per-bias-group framing section (what left / center / right outlets
emphasize) would be a second field in the same response, generated only when
the story has enough coverage on at least two sides. See ``StorySummary``.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

MODEL = "deepseek/deepseek-v4-flash"
# Bump when the prompt or output shape changes, so rows can be compared.
PROMPT_VERSION = 1
_TIMEOUT_SECONDS = 30
# A headline and five short bullets in JSON. Caps a rambling completion.
_MAX_TOKENS = 800

# Membership is added one article at a time, so landing on one of these counts
# means the story just crossed that size. Past the last threshold, only a new
# lead article refreshes the summary.
COUNT_THRESHOLDS = frozenset({3, 5, 10, 20, 40})
PROMPT_ARTICLE_LIMIT = 6
MAX_BULLETS = 5
_EXCERPT_CHARS = 400
_MIN_TITLE_CHARS = 8
_MAX_TITLE_CHARS = 120
_MIN_BULLET_CHARS = 10
_MAX_BULLET_CHARS = 300

logger = logging.getLogger(__name__)
_missing_key_logged = False

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "story_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "bullets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "sources": {"type": "array", "items": {"type": "integer"}},
                            "previous": {"type": ["integer", "null"]},
                        },
                        "required": ["text", "sources", "previous"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["title", "bullets"],
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


@dataclass(frozen=True)
class Bullet:
    text: str
    article_ids: tuple[int, ...]


@dataclass(frozen=True)
class Brief:
    title: str
    bullets: tuple[Bullet, ...]
    lead_article_id: int | None = None


def ordered_excerpts(excerpts: Sequence[ArticleExcerpt]) -> list[ArticleExcerpt]:
    return sorted(excerpts, key=lambda item: (item.published_at, item.article_id))


def lead_article(excerpts: Sequence[ArticleExcerpt]) -> ArticleExcerpt | None:
    """Earliest published article. Its title is the fallback headline."""
    ordered = ordered_excerpts(excerpts)
    return ordered[0] if ordered else None


def prompt_excerpts(
    excerpts: Sequence[ArticleExcerpt], limit: int = PROMPT_ARTICLE_LIMIT
) -> list[ArticleExcerpt]:
    """Lead article, then the most recent others."""
    ordered = ordered_excerpts(excerpts)
    if not ordered or limit < 1:
        return []
    lead = ordered[0]
    rest = ordered[1:]
    if len(rest) > limit - 1:
        keep = {item.article_id for item in rest[-(limit - 1) :]}
        rest = [item for item in rest if item.article_id in keep]
    return [lead, *rest]


def should_refresh(previous: Brief | None, *, member_count: int, lead_article_id: int) -> bool:
    """A story without a summary retries on every new article."""
    if previous is None:
        return True
    if lead_article_id != previous.lead_article_id:
        return True
    return member_count in COUNT_THRESHOLDS


def build_prompt(chosen: Sequence[ArticleExcerpt], previous: Brief | None = None) -> str:
    if not chosen:
        return ""
    lines = [
        "You summarize a Slovenian news story covered by several outlets.",
        "Use the language of the articles (Slovenian, when the articles are Slovenian).",
        "",
        "Return a headline and key-point bullets.",
        "Headline: neutral, factual, and concise, under 100 characters.",
        "Use natural capitalization: capitalize the first letter and proper names only.",
        "No clickbait, no questions, no exclamation marks.",
        (
            f"Bullets: 1 to {MAX_BULLETS} key facts, most important first. Use fewer when the"
            " articles say little. Each bullet is one sentence under 200 characters."
        ),
        "State facts, not opinions. Attribute claims and numbers to whoever made them.",
        "Never name outlets or websites.",
        "For each bullet, list in `sources` the numbers of the articles below that support it.",
    ]
    if previous is not None and previous.bullets:
        lines += [
            "",
            "The story already has this summary, written from earlier articles:",
            f"Headline: {previous.title}",
        ]
        for index, bullet in enumerate(previous.bullets, start=1):
            lines.append(f"P{index}. {bullet.text}")
        lines += [
            "",
            (
                "Keep the headline and bullets that still hold, word for word. When you keep or"
                " revise a bullet, set `previous` to its P number. Change only what the articles"
                " below update or contradict, add bullets for important new facts, and drop"
                " bullets that no longer matter. Set `previous` to null for new bullets."
            ),
        ]
    else:
        lines.append("Set `previous` to null on every bullet.")
    lines += ["", "Articles:"]
    for index, excerpt in enumerate(chosen, start=1):
        lines.append(f"{index}. Title: {_clip(excerpt.title, limit=300) or excerpt.title}")
        deck = _clip(excerpt.deck)
        summary = _clip(excerpt.summary)
        if deck:
            lines.append(f"   Lead: {deck}")
        if summary:
            lines.append(f"   Summary: {summary}")
    return "\n".join(lines)


def parse_title(content: object) -> str | None:
    if not isinstance(content, str):
        return None
    candidate = " ".join(content.split())
    if len(candidate) >= 2 and (
        (candidate[0] == '"' and candidate[-1] == '"')
        or (candidate[0] == "'" and candidate[-1] == "'")
        or (candidate[0] == "«" and candidate[-1] == "»")
    ):
        candidate = candidate[1:-1].strip()
    if not _is_usable_title(candidate):
        return None
    return candidate


def parse_brief(
    content: str,
    chosen: Sequence[ArticleExcerpt],
    previous: Brief | None = None,
) -> Brief | None:
    """Validate the model's JSON. Article numbers become article ids.

    A bullet that continues a previous one keeps that bullet's sources too, so
    facts from articles no longer in the prompt stay attributed.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    title = parse_title(data.get("title"))
    raw_bullets = data.get("bullets")
    if title is None or not isinstance(raw_bullets, list):
        return None
    previous_bullets = previous.bullets if previous is not None else ()
    bullets: list[Bullet] = []
    seen: set[str] = set()
    for item in raw_bullets:
        if not isinstance(item, dict):
            continue
        text = _clean_bullet(item.get("text"))
        if text is None or text.casefold() in seen:
            continue
        ids: list[int] = []
        prior = item.get("previous")
        if _is_index(prior, len(previous_bullets)):
            ids.extend(previous_bullets[prior - 1].article_ids)
        sources = item.get("sources")
        if isinstance(sources, list):
            ids.extend(
                chosen[number - 1].article_id
                for number in sources
                if _is_index(number, len(chosen))
            )
        seen.add(text.casefold())
        bullets.append(Bullet(text=text, article_ids=tuple(dict.fromkeys(ids))))
        if len(bullets) == MAX_BULLETS:
            break
    if not bullets:
        return None
    lead = chosen[0].article_id if chosen else None
    return Brief(title=title, bullets=tuple(bullets), lead_article_id=lead)


def generate_brief(
    excerpts: Sequence[ArticleExcerpt],
    previous: Brief | None = None,
    *,
    complete: Callable[[str], str] | None = None,
) -> Brief | None:
    """Return a new summary, or None when the model is unavailable or unusable."""
    chosen = prompt_excerpts(excerpts)
    prompt = build_prompt(chosen, previous)
    if not prompt:
        return None
    call = complete if complete is not None else _complete
    try:
        raw = call(prompt)
    except _MissingKey:
        return None
    except Exception:
        logger.warning("Story summary generation failed", exc_info=True)
        return None
    if not isinstance(raw, str):
        logger.warning("Story summary generation returned %s", type(raw).__name__)
        return None
    brief = parse_brief(raw, chosen, previous)
    if brief is None:
        logger.warning("Story summary generation returned unusable output: %r", raw[:300])
    return brief


def refresh_brief(
    excerpts: Sequence[ArticleExcerpt],
    previous: Brief | None,
    *,
    complete: Callable[[str], str] | None = None,
) -> Brief | None:
    """New summary when the story changed enough and the model delivered, else None."""
    lead = lead_article(excerpts)
    if lead is None:
        return None
    if not should_refresh(previous, member_count=len(excerpts), lead_article_id=lead.article_id):
        return None
    return generate_brief(excerpts, previous, complete=complete)


def bullets_to_json(bullets: Sequence[Bullet]) -> list[dict]:
    return [{"text": bullet.text, "article_ids": list(bullet.article_ids)} for bullet in bullets]


def bullets_from_json(data: object) -> tuple[Bullet, ...]:
    if not isinstance(data, list):
        return ()
    return tuple(
        Bullet(text=item["text"], article_ids=tuple(item.get("article_ids") or ()))
        for item in data
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    )


def _is_index(value: object, size: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= size


def _clip(text: str | None, limit: int = _EXCERPT_CHARS) -> str | None:
    if text is None:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _clean_bullet(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.split()).lstrip("-•*· ").strip()
    if not _MIN_BULLET_CHARS <= len(cleaned) <= _MAX_BULLET_CHARS:
        return None
    lowered = cleaned.casefold()
    if "http://" in lowered or "https://" in lowered or "www." in lowered:
        return None
    return cleaned


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
            logger.warning("OPENROUTER_API_KEY missing; stories keep the first article's title")
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
        "response_format": _RESPONSE_FORMAT,
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
