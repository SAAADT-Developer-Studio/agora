import json
import logging
from collections.abc import Sequence

from . import llm
from .assign import (
    DEVELOPMENT,
    DIFFERENT,
    JOIN_RELATIONS,
    RELATED_TOPIC,
    RELATIONS,
    SAME_EVENT,
    PromptArticle,
    StoryContext,
    Verdict,
)

MODEL = llm.MODEL

# Two stories merge on the same relations an article joins on: a development
# that seeded its own story belongs with the story it develops.
MERGE_RELATIONS = JOIN_RELATIONS

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

CHOICE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "story_choice",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "story": {"type": "integer"},
                "relation": {"type": "string", "enum": list(RELATIONS)},
            },
            "required": ["story", "relation"],
            "additionalProperties": False,
        },
    },
}

RELATION_FORMAT = {
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
}

logger = logging.getLogger(__name__)
_missing_key_logged = False


def build_prompt(article: PromptArticle, stories: Sequence[StoryContext]) -> str:
    lines = [*_DEFINITIONS, ""]
    for number, story in enumerate(stories, start=1):
        lines.extend([f"Story {number}:", *_story_lines(story), ""])
    lines.append("New article:")
    lines.extend(_article_lines(article))
    lines.extend(
        [
            "",
            "Which story does the new article belong to? Answer with that story's number "
            "and the article's relation to it. When none of the stories is the same "
            "happening or a direct development of it, answer story 0 with the closest "
            "relation (related_topic or different).",
        ]
    )
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


def parse_verdict(content: str, candidates: int) -> Verdict:
    relation = parse_relation(content)
    story = json.loads(content).get("story")
    if not isinstance(story, int) or isinstance(story, bool) or not 0 <= story <= candidates:
        raise ValueError(f"expected story 0..{candidates}, got {content!r}")
    if story == 0:
        # "None of them" with a joining relation is self-contradictory; trust the 0.
        return Verdict(None, relation if relation not in JOIN_RELATIONS else RELATED_TOPIC)
    return Verdict(story - 1, relation)


def choose_story(
    article: PromptArticle,
    stories: Sequence[StoryContext],
    *,
    complete: llm.Complete | None = None,
) -> Verdict | None:
    """Which candidate the article belongs to, or None without an API key."""
    content = _ask(build_prompt(article, stories), CHOICE_FORMAT, complete)
    return None if content is None else parse_verdict(content, len(stories))


def story_relation(
    first: StoryContext, second: StoryContext, *, complete: llm.Complete | None = None
) -> str | None:
    """How story B relates to story A, or None without an API key."""
    content = _ask(build_merge_prompt(first, second), RELATION_FORMAT, complete)
    return None if content is None else parse_relation(content)


def default_complete(response_format: dict) -> llm.Complete:
    return lambda prompt: llm.chat(prompt, response_format=response_format).content


def _ask(prompt: str, response_format: dict, complete: llm.Complete | None) -> str | None:
    global _missing_key_logged
    call = complete if complete is not None else default_complete(response_format)
    try:
        return call(prompt)
    except llm.MissingKey:
        if not _missing_key_logged:
            logger.warning("OPENROUTER_API_KEY missing; gray-band articles will seed")
            _missing_key_logged = True
        return None
