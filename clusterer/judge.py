import json
import logging
import os
import urllib.error
import urllib.request

from .assign import PromptArticle, StoryContext

MODEL = "deepseek/deepseek-v4-flash"
_TIMEOUT_SECONDS = 30

SAME_EVENT = "same_event"
DEVELOPMENT = "development"
RELATED_TOPIC = "related_topic"
DIFFERENT = "different"
RELATIONS = (SAME_EVENT, DEVELOPMENT, RELATED_TOPIC, DIFFERENT)
# An article joins on either; two stories merge only when they are the same event.
JOIN_RELATIONS = frozenset({SAME_EVENT, DEVELOPMENT})
MERGE_RELATIONS = frozenset({SAME_EVENT})

_DEFINITIONS = [
    "You group Slovenian news into stories.",
    "",
    "A story is one real-world happening and its direct developments: the event, what "
    "was said at it, its outcome, and the immediate reactions to it.",
    "",
    "Relations:",
    f"- {SAME_EVENT}: reports the same happening.",
    f"- {DEVELOPMENT}: a direct follow-up of that happening: its outcome, a reaction to "
    "it, or a consequence of it.",
    f"- {RELATED_TOPIC}: the same topic, people, or place, but a different happening. "
    "This includes opinion columns and commentary, explainers and background pieces, "
    "live blogs that only mention the story, and other events in the same war, campaign, "
    "or season.",
    f"- {DIFFERENT}: unrelated.",
]

logger = logging.getLogger(__name__)
_missing_key_logged = False


def build_prompt(article: PromptArticle, story: StoryContext) -> str:
    lines = [*_DEFINITIONS, "", "Story:", *_story_lines(story), "", "New article:"]
    lines.extend(_article_lines(article))
    lines.extend(["", "How does the new article relate to the story?"])
    return "\n".join(lines)


def build_merge_prompt(first: StoryContext, second: StoryContext) -> str:
    lines = [*_DEFINITIONS, "", "Story A:", *_story_lines(first), "", "Story B:"]
    lines.extend(_story_lines(second))
    lines.extend(["", "How does story B relate to story A?"])
    return "\n".join(lines)


def _story_lines(story: StoryContext) -> list[str]:
    lines: list[str] = []
    if story.headline:
        lines.append(f"Headline: {story.headline}")
    if story.bullets:
        lines.append("Key points:")
        lines.extend(f"- {bullet}" for bullet in story.bullets)
    if story.members:
        lines.append("Articles:")
    for index, member in enumerate(story.members, start=1):
        first, *rest = _article_lines(member)
        lines.append(f"{index}. {first}")
        lines.extend(f"   {line}" for line in rest)
    return lines


def _article_lines(article: PromptArticle) -> list[str]:
    date = f"[{article.published_at:%Y-%m-%d}] " if article.published_at else ""
    lines = [f"{date}Title: {article.title}"]
    if article.summary and article.summary.strip():
        lines.append(f"Summary: {article.summary}")
    return lines


def parse_relation(content: str) -> str:
    data = json.loads(content)
    relation = data.get("relation") if isinstance(data, dict) else None
    if relation not in RELATIONS:
        raise ValueError(f"expected {{\"relation\": one of {RELATIONS}}}, got {content!r}")
    return relation


def same_happening(article: PromptArticle, story: StoryContext) -> bool:
    relation = _ask(build_prompt(article, story))
    return relation in JOIN_RELATIONS


def same_story(first: StoryContext, second: StoryContext) -> bool:
    relation = _ask(build_merge_prompt(first, second))
    return relation in MERGE_RELATIONS


def _ask(prompt: str) -> str | None:
    """The judge's relation, or None without an API key."""
    global _missing_key_logged
    primary = os.getenv("OPENROUTER_API_KEY") or None
    if not primary:
        if not _missing_key_logged:
            logger.warning("OPENROUTER_API_KEY missing; gray-band articles will seed")
            _missing_key_logged = True
        return None
    try:
        return _complete(primary, prompt)
    except urllib.error.HTTPError as exc:
        fallback = os.getenv("OPENROUTER_FALLBACK_API_KEY") or os.getenv(
            "OPENROUTER_API_KEY_FALLBACK"
        )
        if exc.code == 402 and fallback:
            return _complete(fallback, prompt)
        raise


def _complete(api_key: str, prompt: str) -> str:
    url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "reasoning": {"enabled": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "story_relation",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"relation": {"type": "string", "enum": list(RELATIONS)}},
                    "required": ["relation"],
                    "additionalProperties": False,
                },
            },
        },
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
    return parse_relation(content)
