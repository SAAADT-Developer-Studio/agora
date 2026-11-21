"""Story summary step: one LLM call for a headline, a lede, and key-point bullets.

The lede is the five Ws in a sentence or two: what happened, where, when (as a
date, never "yesterday"), who, and how. A reader landing on a story days later
must see when it happened without opening an article.

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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import llm

MODEL = llm.MODEL
# Bump when the prompt or output shape changes, so rows can be compared.
PROMPT_VERSION = 3
# A headline, a lede, and five short bullets in JSON. Caps a rambling completion.
_MAX_TOKENS = 900

# Membership is added one article at a time, so landing on one of these counts
# means the story just crossed that size. Past the last one, every
# ``COUNT_STEP`` more articles refresh it too.
COUNT_THRESHOLDS = frozenset({3, 5, 10, 20, 40})
COUNT_STEP = 20
# A summary older than this is refreshed by the next article published after it,
# so a story that keeps moving never shows day-old facts.
STALE_AFTER = timedelta(hours=6)
PROMPT_ARTICLE_LIMIT = 6
MAX_BULLETS = 5
_EXCERPT_CHARS = 400
_MIN_TITLE_CHARS = 8
_MAX_TITLE_CHARS = 120
_MIN_BULLET_CHARS = 10
_MAX_BULLET_CHARS = 300
_MIN_LEDE_CHARS = 20
_MAX_LEDE_CHARS = 400

logger = logging.getLogger(__name__)
_missing_key_logged = False

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "story_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "lede": {"type": "string"},
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
            "required": ["title", "lede", "bullets"],
            "additionalProperties": False,
        },
    },
}

_JUNK_PREFIXES = ("here is", "here's", "headline:", "title:", "naslov:", "naslov je")


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
    # When the summary was written; None for one not stored yet.
    created_at: datetime | None = None
    # What, where, when, who, how. None on summaries written before it existed.
    lede: str | None = None


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


def should_refresh(
    previous: Brief | None,
    *,
    member_count: int,
    lead_article_id: int,
    newest_published_at: datetime | None = None,
    now: datetime | None = None,
) -> bool:
    """A story without a summary retries on every new article."""
    if previous is None:
        return True
    if lead_article_id != previous.lead_article_id:
        return True
    if member_count in COUNT_THRESHOLDS:
        return True
    if member_count > max(COUNT_THRESHOLDS) and member_count % COUNT_STEP == 0:
        return True
    written = previous.created_at
    return (
        written is not None
        and now is not None
        and newest_published_at is not None
        and now - written >= STALE_AFTER
        and newest_published_at > written
    )


def build_prompt(chosen: Sequence[ArticleExcerpt], previous: Brief | None = None) -> str:
    if not chosen:
        return ""
    lines = [
        "You summarize a Slovenian news story covered by several outlets.",
        "Use the language of the articles (Slovenian, when the articles are Slovenian).",
        "",
        "Return a headline, a lede, and key-point bullets.",
        "Headline: neutral, factual, and concise, under 100 characters.",
        "Use natural capitalization: capitalize the first letter and proper names only.",
        "No clickbait, no questions, no exclamation marks.",
        (
            "Lede: one or two short sentences, under 300 characters, saying what happened,"
            " where, when, who was involved, and how. Give the date of the event as day and"
            " month, e.g. '11. oktobra'; add the time of day when the articles give it."
            " Never write relative dates such as 'yesterday', 'on Sunday', or 'this week'."
        ),
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
        if previous.lede:
            lines.append(f"Lede: {previous.lede}")
        for index, bullet in enumerate(previous.bullets, start=1):
            lines.append(f"P{index}. {bullet.text}")
        lines += [
            "",
            (
                "Keep the headline, lede, and bullets that still hold, word for word. When you keep"
                " or revise a bullet, set `previous` to its P number. Rewrite the headline, the"
                " lede, and any bullet that the articles below update or contradict, add bullets"
                " for important new facts, and drop bullets that no longer matter. Set `previous`"
                " to null for new bullets."
            ),
        ]
    else:
        lines.append("Set `previous` to null on every bullet.")
    lines += [
        "",
        (
            "The articles are oldest first. When they disagree on a number or on what"
            " happened, the most recent article is right; the headline must reflect the"
            " latest state of the story."
        ),
        (
            "Each article is stamped with its publication time (UTC). Turn the relative dates"
            " in its text into calendar dates using that stamp: 'yesterday' in an article"
            " published on Mon 2026-10-12 means 11 October, and 'on Tuesday' means 13 October."
        ),
        "",
        "Articles:",
    ]
    for index, excerpt in enumerate(chosen, start=1):
        title = _clip(excerpt.title, limit=300) or excerpt.title
        lines.append(f"{index}. [{excerpt.published_at:%a %Y-%m-%d %H:%M}] Title: {title}")
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
    lede = _clean_lede(data.get("lede"))
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
    return Brief(title=title, bullets=tuple(bullets), lead_article_id=lead, lede=lede)


def generate_brief(
    excerpts: Sequence[ArticleExcerpt],
    previous: Brief | None = None,
    *,
    complete: llm.Complete | None = None,
) -> Brief | None:
    """Return a new summary, or None when the model is unavailable or unusable."""
    chosen = prompt_excerpts(excerpts)
    prompt = build_prompt(chosen, previous)
    if not prompt:
        return None
    call = complete if complete is not None else _complete
    try:
        raw = call(prompt)
    except llm.MissingKey:
        global _missing_key_logged
        if not _missing_key_logged:
            logger.warning("OPENROUTER_API_KEY missing; stories keep the first article's title")
            _missing_key_logged = True
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
    complete: llm.Complete | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> Brief | None:
    """New summary when the story changed enough and the model delivered, else None.

    ``force`` skips the change check, e.g. after another story merged in.
    """
    lead = lead_article(excerpts)
    if lead is None:
        return None
    newest = max(excerpt.published_at for excerpt in excerpts)
    if not force and not should_refresh(
        previous,
        member_count=len(excerpts),
        lead_article_id=lead.article_id,
        newest_published_at=newest,
        now=now,
    ):
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


def _clean_lede(text: object) -> str | None:
    """A missing or unusable lede leaves the rest of the summary standing."""
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.split())
    if not _MIN_LEDE_CHARS <= len(cleaned) <= _MAX_LEDE_CHARS:
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
    return llm.chat(prompt, response_format=RESPONSE_FORMAT, max_tokens=_MAX_TOKENS).content
