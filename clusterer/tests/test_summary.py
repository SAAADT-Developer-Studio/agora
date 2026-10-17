import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

import clusterer.summary as summary
from clusterer.summary import (
    ArticleExcerpt,
    Brief,
    Bullet,
    build_prompt,
    bullets_from_json,
    bullets_to_json,
    generate_brief,
    parse_brief,
    parse_title,
    prompt_excerpts,
    refresh_brief,
    should_refresh,
)

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
HEADLINE = "Vlada zvišala minimalno plačo za prihodnje leto"
FACT = "Minimalna plača bo januarja zrasla za šest odstotkov."


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


def _response(title: str = HEADLINE, bullets: list[dict] | None = None) -> str:
    if bullets is None:
        bullets = [{"text": FACT, "sources": [1], "previous": None}]
    return json.dumps({"title": title, "bullets": bullets})


PREVIOUS = Brief(
    title=HEADLINE,
    bullets=(Bullet(text=FACT, article_ids=(1, 2)),),
    lead_article_id=1,
)


def test_prompt_includes_lead_and_summary_and_skips_blanks() -> None:
    text = build_prompt(
        [
            _excerpt(1, "Prvi naslov", deck="  ", summary=None),
            _excerpt(2, "Drugi naslov", deck="Vodilo", summary="Povzetek", hours=1),
        ]
    )

    assert text.startswith("You summarize a Slovenian news story")
    assert "language of the articles" in text
    assert "under 100 characters" in text
    assert "No clickbait" in text
    assert "Never name outlets" in text
    assert "Set `previous` to null on every bullet." in text
    assert (
        "1. Title: Prvi naslov\n2. Title: Drugi naslov\n   Lead: Vodilo\n   Summary: Povzetek"
        in text
    )
    assert "Lead:  " not in text


def test_prompt_carries_the_previous_summary() -> None:
    text = build_prompt([_excerpt(1, "Prvi")], PREVIOUS)

    assert f"Headline: {HEADLINE}" in text
    assert f"P1. {FACT}" in text
    assert "word for word" in text
    assert "on every bullet" not in text


def test_prompt_keeps_the_lead_and_the_latest_articles() -> None:
    excerpts = [_excerpt(index, f"t{index}", hours=index) for index in range(1, 9)]

    chosen = [item.article_id for item in prompt_excerpts(excerpts, limit=6)]

    assert chosen == [1, 4, 5, 6, 7, 8]


def test_prompt_clips_a_long_summary() -> None:
    text = build_prompt([_excerpt(1, "Naslov", summary="beseda " * 200)])

    assert "…" in text
    assert "beseda " * 200 not in text


def test_parse_title_strips_whitespace_and_quotes() -> None:
    assert parse_title(f"  {HEADLINE}  ") == HEADLINE
    assert parse_title(f'"{HEADLINE}"') == HEADLINE


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "Kratko",
        HEADLINE + "!",
        "Bo vlada dvignila plače?",
        "A" * 121,
        "Here is a generated headline",
        "https://example.com/story",
        "# Naslov novice o plačah",
        12,
        None,
    ],
)
def test_parse_title_rejects_junk(raw: object) -> None:
    assert parse_title(raw) is None


def test_parse_brief_maps_article_numbers_to_ids() -> None:
    chosen = [_excerpt(7, "Prvi"), _excerpt(9, "Drugi", hours=1)]
    raw = _response(
        bullets=[
            {"text": f"- {FACT}", "sources": [2, 1, 2, 5, 0], "previous": None},
            {"text": "Sindikati so dvig označili za premajhen.", "sources": [], "previous": None},
        ]
    )

    brief = parse_brief(raw, chosen)

    assert brief == Brief(
        title=HEADLINE,
        bullets=(
            Bullet(text=FACT, article_ids=(9, 7)),
            Bullet(text="Sindikati so dvig označili za premajhen.", article_ids=()),
        ),
        lead_article_id=7,
    )


def test_parse_brief_keeps_sources_of_a_continued_bullet() -> None:
    chosen = [_excerpt(1, "Prvi"), _excerpt(5, "Peti", hours=4)]
    raw = _response(bullets=[{"text": FACT, "sources": [2], "previous": 1}])

    brief = parse_brief(raw, chosen, PREVIOUS)

    assert brief is not None
    assert brief.bullets == (Bullet(text=FACT, article_ids=(1, 2, 5)),)


def test_parse_brief_drops_bad_bullets_and_caps_the_count() -> None:
    chosen = [_excerpt(1, "Prvi")]
    good = [
        {"text": f"Dejstvo številka {index} o plačah.", "sources": [1], "previous": 3}
        for index in range(8)
    ]
    raw = _response(
        bullets=[
            {"text": "kratko", "sources": [1], "previous": None},
            {"text": "Glej https://example.com za več.", "sources": [1], "previous": None},
            "not an object",
            {"text": good[0]["text"].upper(), "sources": [1], "previous": None},
            *good,
        ]
    )

    brief = parse_brief(raw, chosen)

    assert brief is not None
    assert [bullet.text for bullet in brief.bullets] == [
        good[0]["text"].upper(),
        *[item["text"] for item in good[1:5]],
    ]


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        json.dumps(["naslov"]),
        _response(title="Kratko"),
        _response(bullets=[]),
        _response(bullets=[{"text": "kratko", "sources": [], "previous": None}]),
        json.dumps({"title": HEADLINE}),
    ],
)
def test_parse_brief_rejects_unusable_output(raw: str) -> None:
    assert parse_brief(raw, [_excerpt(1, "Prvi")]) is None


@pytest.mark.parametrize(
    ("previous", "count", "lead", "expected"),
    [
        (None, 1, 1, True),
        (None, 4, 1, True),
        (PREVIOUS, 2, 1, False),
        (PREVIOUS, 4, 1, False),
        (PREVIOUS, 3, 1, True),
        (PREVIOUS, 5, 1, True),
        (PREVIOUS, 10, 1, True),
        (PREVIOUS, 20, 1, True),
        (PREVIOUS, 40, 1, True),
        (PREVIOUS, 21, 1, False),
        (PREVIOUS, 2, 9, True),
    ],
)
def test_should_refresh(previous, count, lead, expected) -> None:
    assert should_refresh(previous, member_count=count, lead_article_id=lead) is expected


def test_new_story_gets_a_summary() -> None:
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return _response()

    brief = refresh_brief([_excerpt(7, "Prvi naslov", deck="Kratek uvod")], None, complete=complete)

    assert prompts and "Prvi naslov" in prompts[0]
    assert brief == Brief(
        title=HEADLINE, bullets=(Bullet(text=FACT, article_ids=(7,)),), lead_article_id=7
    )


def test_llm_failure_returns_nothing() -> None:
    def complete(_prompt: str) -> str:
        raise RuntimeError("openrouter down")

    assert refresh_brief([_excerpt(7, "Prvi naslov")], None, complete=complete) is None


def test_junk_response_returns_nothing() -> None:
    brief = refresh_brief(
        [_excerpt(7, "Prvi naslov")], None, complete=lambda _prompt: "Sure! Click here"
    )

    assert brief is None


def test_small_update_does_not_call_the_model() -> None:
    def complete(_prompt: str) -> str:
        raise AssertionError("should not regenerate")

    brief = refresh_brief(
        [_excerpt(1, "Prvi"), _excerpt(2, "Drugi", hours=1)], PREVIOUS, complete=complete
    )

    assert brief is None


def test_lead_change_regenerates_with_the_previous_summary() -> None:
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return _response(title="Nov skupni naslov o rasti plač")

    excerpts = [_excerpt(1, "Kasnejši članek", hours=2), _excerpt(9, "Zgodnejši članek")]
    brief = refresh_brief(excerpts, PREVIOUS, complete=complete)

    assert len(prompts) == 1
    assert f"P1. {FACT}" in prompts[0]
    assert brief is not None
    assert brief.title == "Nov skupni naslov o rasti plač"
    assert brief.lead_article_id == 9


def test_bullets_round_trip_through_json() -> None:
    bullets = (Bullet(text=FACT, article_ids=(3, 1)), Bullet(text="Drugo dejstvo.", article_ids=()))

    stored = bullets_to_json(bullets)

    assert stored == [
        {"text": FACT, "article_ids": [3, 1]},
        {"text": "Drugo dejstvo.", "article_ids": []},
    ]
    assert bullets_from_json(stored) == bullets
    assert bullets_from_json(None) == ()


def test_missing_key_does_not_call_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    summary._missing_key_logged = False

    def urlopen(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("should not call OpenRouter")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert generate_brief([_excerpt(1, "Prvi naslov")]) is None


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
        assert body["response_format"]["json_schema"]["name"] == "story_summary"
        payload = {"choices": [{"message": {"content": _response()}}]}
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    brief = generate_brief([_excerpt(1, "Prvi naslov")])

    assert brief is not None and brief.title == HEADLINE
    assert calls == ["Bearer primary", "Bearer fallback"]


def test_http_error_does_not_escape_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "primary")
    monkeypatch.delenv("OPENROUTER_FALLBACK_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY_FALLBACK", raising=False)

    def urlopen(request: urllib.request.Request, timeout: float = 0) -> object:
        raise urllib.error.HTTPError(request.full_url, 500, "Error", hdrs=None, fp=io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert refresh_brief([_excerpt(1, "Prvi naslov")], None) is None
