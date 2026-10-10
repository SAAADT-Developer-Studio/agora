import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

import clusterer.titles as titles
from clusterer.titles import (
    TITLE_SOURCE_ARTICLE,
    TITLE_SOURCE_GENERATED,
    ArticleExcerpt,
    build_title_prompt,
    generate_title,
    parse_title,
    prompt_excerpts,
    refresh_story_title,
    should_generate_title,
)

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
HEADLINE = "Vlada zvišala minimalno plačo za prihodnje leto"


def _excerpt(
    article_id: int,
    title: str,
    *,
    deck: str | None = None,
    summary: str | None = None,
    hours: int = 0,
) -> ArticleExcerpt:
    return ArticleExcerpt(
        article_id=article_id,
        title=title,
        deck=deck,
        summary=summary,
        published_at=NOW + timedelta(hours=hours),
    )


class _Story:
    def __init__(
        self,
        title: str,
        *,
        title_source: str | None = None,
        title_lead_article_id: int | None = None,
    ) -> None:
        self.id = 1
        self.title = title
        self.title_source = title_source
        self.title_generated_at = None
        self.title_lead_article_id = title_lead_article_id


def test_prompt_includes_lead_and_summary_and_skips_blanks() -> None:
    text = build_title_prompt(
        [
            _excerpt(1, "Prvi naslov", deck="  ", summary=None),
            _excerpt(2, "Drugi naslov", deck="Vodilo", summary="Povzetek", hours=1),
        ]
    )

    assert text.startswith("You write headlines for a Slovenian news story.\n")
    assert "language of the articles" in text
    assert "under 100 characters" in text
    assert "No clickbait" in text
    assert "outlet" in text
    assert (
        "1. Title: Prvi naslov\n2. Title: Drugi naslov\n   Lead: Vodilo\n   Summary: Povzetek"
        in text
    )
    assert "Lead:  " not in text


def test_prompt_keeps_the_lead_and_the_latest_articles() -> None:
    excerpts = [_excerpt(index, f"t{index}", hours=index) for index in range(1, 9)]

    chosen = [item.article_id for item in prompt_excerpts(excerpts, limit=6)]

    assert chosen == [1, 4, 5, 6, 7, 8]


def test_prompt_clips_a_long_summary() -> None:
    text = build_title_prompt([_excerpt(1, "Naslov", summary="beseda " * 200)])

    assert "…" in text
    assert "beseda " * 200 not in text


def test_parse_title_accepts_json_and_a_bare_headline() -> None:
    assert parse_title(json.dumps({"title": f"  {HEADLINE}  "})) == HEADLINE
    assert parse_title(f'"{HEADLINE}"') == HEADLINE


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "Kratko",
        json.dumps({"title": HEADLINE + "!"}),
        json.dumps({"title": "Bo vlada dvignila plače?"}),
        json.dumps({"title": "A" * 121}),
        json.dumps({"title": "Here is a generated headline"}),
        json.dumps({"title": "https://example.com/story"}),
        "{not json",
        json.dumps({"title": 12}),
        json.dumps(["naslov"]),
        "# Naslov novice o plačah",
    ],
)
def test_parse_title_rejects_junk(raw: str) -> None:
    assert parse_title(raw) is None


@pytest.mark.parametrize(
    ("source", "stored_lead", "count", "lead", "is_new", "expected"),
    [
        (None, None, 1, 1, True, True),
        (TITLE_SOURCE_ARTICLE, None, 2, 1, False, True),
        (None, None, 4, 1, False, True),
        (TITLE_SOURCE_GENERATED, 1, 2, 1, False, False),
        (TITLE_SOURCE_GENERATED, 1, 4, 1, False, False),
        (TITLE_SOURCE_GENERATED, 1, 3, 1, False, True),
        (TITLE_SOURCE_GENERATED, 1, 5, 1, False, True),
        (TITLE_SOURCE_GENERATED, 1, 10, 1, False, True),
        (TITLE_SOURCE_GENERATED, 1, 20, 1, False, True),
        (TITLE_SOURCE_GENERATED, 1, 40, 1, False, True),
        (TITLE_SOURCE_GENERATED, 1, 21, 1, False, False),
        (TITLE_SOURCE_GENERATED, 1, 2, 9, False, True),
    ],
)
def test_should_generate_title(source, stored_lead, count, lead, is_new, expected) -> None:
    assert (
        should_generate_title(
            title_source=source,
            stored_lead_article_id=stored_lead,
            member_count=count,
            lead_article_id=lead,
            is_new=is_new,
        )
        is expected
    )


def test_new_story_stores_the_generated_title() -> None:
    story = _Story("Prvi naslov")
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"title": HEADLINE})

    refresh_story_title(
        story,
        [_excerpt(7, "Prvi naslov", deck="Kratek uvod")],
        is_new=True,
        complete=complete,
        now=NOW,
    )

    assert prompts and "Prvi naslov" in prompts[0]
    assert story.title == HEADLINE
    assert story.title_source == TITLE_SOURCE_GENERATED
    assert story.title_generated_at == NOW
    assert story.title_lead_article_id == 7


def test_llm_failure_keeps_the_first_article_title() -> None:
    story = _Story("Prvi naslov")

    def complete(_prompt: str) -> str:
        raise RuntimeError("openrouter down")

    refresh_story_title(story, [_excerpt(7, "Prvi naslov")], is_new=True, complete=complete)

    assert story.title == "Prvi naslov"
    assert story.title_source == TITLE_SOURCE_ARTICLE
    assert story.title_generated_at is None
    assert story.title_lead_article_id is None


def test_junk_response_keeps_the_first_article_title() -> None:
    story = _Story("Prvi naslov")

    refresh_story_title(
        story,
        [_excerpt(7, "Prvi naslov")],
        is_new=True,
        complete=lambda _prompt: "Sure! Click here",
    )

    assert story.title == "Prvi naslov"
    assert story.title_source == TITLE_SOURCE_ARTICLE


def test_failed_refresh_keeps_an_existing_generated_title() -> None:
    story = _Story(HEADLINE, title_source=TITLE_SOURCE_GENERATED, title_lead_article_id=1)
    story.title_generated_at = NOW

    refresh_story_title(
        story,
        [_excerpt(1, "Prvi"), _excerpt(2, "Drugi", hours=1), _excerpt(3, "Tretji", hours=2)],
        is_new=False,
        complete=lambda _prompt: "not a headline!!!",
        now=NOW + timedelta(days=1),
    )

    assert story.title == HEADLINE
    assert story.title_source == TITLE_SOURCE_GENERATED
    assert story.title_generated_at == NOW
    assert story.title_lead_article_id == 1


def test_small_update_does_not_call_the_model() -> None:
    story = _Story(HEADLINE, title_source=TITLE_SOURCE_GENERATED, title_lead_article_id=1)

    def complete(_prompt: str) -> str:
        raise AssertionError("should not regenerate")

    refresh_story_title(
        story,
        [_excerpt(1, "Prvi"), _excerpt(2, "Drugi", hours=1)],
        is_new=False,
        complete=complete,
    )

    assert story.title == HEADLINE


def test_threshold_and_lead_change_regenerate() -> None:
    calls: list[int] = []

    def complete(_prompt: str) -> str:
        calls.append(1)
        return json.dumps({"title": "Nov skupni naslov o rasti plač"})

    story = _Story(HEADLINE, title_source=TITLE_SOURCE_GENERATED, title_lead_article_id=2)
    excerpts = [
        _excerpt(2, "Kasnejši članek", hours=2),
        _excerpt(9, "Zgodnejši članek", hours=0),
    ]
    refresh_story_title(story, excerpts, is_new=False, complete=complete, now=NOW)

    assert calls == [1]
    assert story.title == "Nov skupni naslov o rasti plač"
    assert story.title_lead_article_id == 9
    assert story.title_generated_at == NOW


def test_missing_key_does_not_call_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    titles._missing_key_logged = False

    def urlopen(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("should not call OpenRouter")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert generate_title([_excerpt(1, "Prvi naslov")]) is None


def test_credit_error_uses_fallback_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "primary")
    monkeypatch.setenv("OPENROUTER_FALLBACK_API_KEY", "fallback")
    calls: list[str | None] = []

    def urlopen(request: urllib.request.Request, timeout: float = 0) -> object:
        calls.append(request.get_header("Authorization"))
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url, 402, "Payment Required", hdrs=None, fp=io.BytesIO(b"")
            )
        body = json.loads(request.data.decode())
        assert body["model"] == "deepseek/deepseek-v4-flash"
        assert body["reasoning"] == {"enabled": False}
        assert body["response_format"]["json_schema"]["name"] == "story_title"
        payload = {"choices": [{"message": {"content": json.dumps({"title": HEADLINE})}}]}
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert generate_title([_excerpt(1, "Prvi naslov")]) == HEADLINE
    assert calls == ["Bearer primary", "Bearer fallback"]


def test_http_error_does_not_escape_title_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "primary")
    monkeypatch.delenv("OPENROUTER_FALLBACK_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY_FALLBACK", raising=False)

    def urlopen(request: urllib.request.Request, timeout: float = 0) -> object:
        raise urllib.error.HTTPError(request.full_url, 500, "Error", hdrs=None, fp=io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    story = _Story("Prvi naslov")

    refresh_story_title(story, [_excerpt(1, "Prvi naslov")], is_new=True)

    assert story.title == "Prvi naslov"
    assert story.title_source == TITLE_SOURCE_ARTICLE
