import io
import json
import urllib.error
import urllib.request

import pytest

import clusterer.judge as judge
from clusterer.judge import build_prompt, parse_same, same_happening


def test_prompt_omits_blank_summaries() -> None:
    text = build_prompt("Title", "  ", [("A", None), ("B", "sum")])

    assert text.startswith("You group Slovenian news into stories.\n")
    assert "New article:\nTitle: Title\n\nNearest story:\n1. Title: A\n2. Title: B\n   Summary: sum\n" in text
    assert text.endswith("\nIs the new article the same happening as that story?")


def test_parse_same() -> None:
    assert parse_same('{"same": true}') is True
    assert parse_same('{"same": false}') is False


def test_parse_same_rejects_non_bool() -> None:
    with pytest.raises(ValueError):
        parse_same('{"same": "yes"}')


def test_missing_key_seeds_without_calling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    judge._missing_key_logged = False

    def urlopen(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("should not call OpenRouter")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert same_happening("t", "s", [("a", "b")]) is False


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
        payload = {"choices": [{"message": {"content": json.dumps({"same": True})}}]}
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert same_happening("t", "s", [("a", "b")]) is True
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
        same_happening("t", None, [])
    assert calls == ["Bearer primary"]
