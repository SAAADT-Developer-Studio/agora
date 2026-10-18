import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pytest

import clusterer.judge as judge
from clusterer.assign import PromptArticle, StoryContext
from clusterer.judge import (
    build_merge_prompt,
    build_prompt,
    parse_relation,
    same_happening,
    same_story,
)

_DAY = datetime(2026, 10, 11, 9, tzinfo=timezone.utc)
_STORY = StoryContext(
    headline="Referendumi 11. oktobra",
    bullets=("Udeležba 54 %", "Zakon zavrnjen"),
    members=(PromptArticle("A", None, _DAY), PromptArticle("B", "sum")),
)


def _reply(relation: str) -> io.BytesIO:
    payload = {"choices": [{"message": {"content": json.dumps({"relation": relation})}}]}
    return io.BytesIO(json.dumps(payload).encode())


def test_prompt_shows_brief_dated_members_and_omits_blank_summaries() -> None:
    text = build_prompt(PromptArticle("Title", "  ", _DAY), _STORY)

    assert text.startswith("You group Slovenian news into stories.\n")
    assert "opinion columns" in text
    assert (
        "Story:\nHeadline: Referendumi 11. oktobra\nKey points:\n- Udeležba 54 %\n"
        "- Zakon zavrnjen\nArticles:\n1. [2026-10-11] Title: A\n2. Title: B\n"
        "   Summary: sum\n\nNew article:\n[2026-10-11] Title: Title\n"
    ) in text
    assert text.endswith("\nHow does the new article relate to the story?")


def test_merge_prompt_shows_both_stories() -> None:
    other = StoryContext(headline=None, bullets=(), members=(PromptArticle("C", None),))

    text = build_merge_prompt(_STORY, other)

    assert "Story A:\nHeadline: Referendumi 11. oktobra\n" in text
    assert "Story B:\nArticles:\n1. Title: C\n" in text
    assert text.endswith("\nHow does story B relate to story A?")


def test_parse_relation() -> None:
    assert parse_relation('{"relation": "same_event"}') == "same_event"
    assert parse_relation('{"relation": "related_topic"}') == "related_topic"


def test_parse_relation_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        parse_relation('{"relation": "yes"}')
    with pytest.raises(ValueError):
        parse_relation('{"same": true}')


@pytest.mark.parametrize(
    ("relation", "joins", "merges"),
    [
        ("same_event", True, True),
        ("development", True, False),
        ("related_topic", False, False),
        ("different", False, False),
    ],
)
def test_relations_map_to_join_and_merge(
    monkeypatch: pytest.MonkeyPatch, relation: str, joins: bool, merges: bool
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "primary")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _reply(relation))

    assert same_happening(PromptArticle("t", "s"), _STORY) is joins
    assert same_story(_STORY, _STORY) is merges


def test_missing_key_seeds_without_calling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    judge._missing_key_logged = False

    def urlopen(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("should not call OpenRouter")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert same_happening(PromptArticle("t", "s"), _STORY) is False
    assert same_story(_STORY, _STORY) is False


def test_credit_error_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "primary")
    monkeypatch.setenv("OPENROUTER_FALLBACK_API_KEY", "fallback")
    calls: list[str | None] = []

    def urlopen(request: urllib.request.Request, timeout: float = 0) -> object:
        calls.append(request.get_header("Authorization"))
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url, 402, "Payment Required", hdrs=None, fp=io.BytesIO(b"")
            )
        return _reply("same_event")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert same_happening(PromptArticle("t", "s"), _STORY) is True
    assert calls == ["Bearer primary", "Bearer fallback"]


def test_other_http_error_does_not_use_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "primary")
    monkeypatch.setenv("OPENROUTER_FALLBACK_API_KEY", "fallback")
    calls: list[str | None] = []

    def urlopen(request: urllib.request.Request, timeout: float = 0) -> object:
        calls.append(request.get_header("Authorization"))
        raise urllib.error.HTTPError(
            request.full_url, 500, "Error", hdrs=None, fp=io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    with pytest.raises(urllib.error.HTTPError):
        same_happening(PromptArticle("t", None), _STORY)
    assert calls == ["Bearer primary"]
