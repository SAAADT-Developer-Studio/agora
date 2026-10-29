import asyncio

import httpx
import openai
import pytest
from langchain_core.runnables import Runnable
from langchain_core.runnables.fallbacks import RunnableWithFallbacks
from langchain_core.runnables.retry import RunnableRetry

from app import config
from app.openrouter import _with_connection_retry, create_openrouter_chat_model
from app.pipeline.analyzer import ArticleAnalysis

_RETRY_EXCEPTIONS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


def _assert_retry(runnable):
    assert isinstance(runnable, RunnableRetry)
    assert runnable.max_attempt_number == 5
    assert runnable.wait_exponential_jitter is True
    assert runnable.retry_exception_types == _RETRY_EXCEPTIONS


def _assert_sdk_retries_disabled(chat):
    assert chat.max_retries == 0
    assert chat.request_timeout == 60


def _iter_chats(runnable):
    name = type(runnable).__name__
    if name == "ChatOpenAI":
        yield runnable
        return
    if isinstance(runnable, RunnableWithFallbacks):
        yield from _iter_chats(runnable.runnable)
        for fallback in runnable.fallbacks:
            yield from _iter_chats(fallback)
        return
    if isinstance(runnable, RunnableRetry) or hasattr(runnable, "bound"):
        bound = getattr(runnable, "bound", None)
        if bound is not None and bound is not runnable:
            yield from _iter_chats(bound)
            if isinstance(runnable, RunnableRetry):
                return
    steps = getattr(runnable, "steps", None)
    if steps:
        for step in steps:
            yield from _iter_chats(step)


@pytest.fixture
def openrouter_keys(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "primary-key")
    monkeypatch.setattr(config, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(config, "OPENROUTER_FALLBACK_API_KEY", "fallback-key")


def test_retry_wrapper_is_configured_before_fallbacks(openrouter_keys):
    model = create_openrouter_chat_model()

    assert isinstance(model, RunnableWithFallbacks)
    assert model.exceptions_to_handle == (openai.APIStatusError,)
    _assert_retry(model.runnable)
    _assert_sdk_retries_disabled(model.runnable.bound)
    assert len(model.fallbacks) == 1
    _assert_retry(model.fallbacks[0])
    _assert_sdk_retries_disabled(model.fallbacks[0].bound)


def test_retry_wrapper_without_fallback_key(openrouter_keys, monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_FALLBACK_API_KEY", None)

    model = create_openrouter_chat_model()

    assert not isinstance(model, RunnableWithFallbacks)
    _assert_retry(model)
    _assert_sdk_retries_disabled(model.bound)


def test_structured_output_keeps_retry_and_status_fallback(openrouter_keys):
    model = create_openrouter_chat_model()

    structured = model.with_structured_output(ArticleAnalysis)

    assert isinstance(structured, RunnableWithFallbacks)
    assert structured.exceptions_to_handle == (openai.APIStatusError,)
    _assert_retry(structured.runnable)
    _assert_retry(structured.fallbacks[0])
    chats = list(_iter_chats(structured))
    assert len(chats) >= 2
    for chat in chats:
        _assert_sdk_retries_disabled(chat)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def _connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=_request())


def _server_error() -> openai.InternalServerError:
    response = httpx.Response(500, request=_request())
    return openai.InternalServerError("upstream", response=response, body=None)


class _Scripted(Runnable):
    """Returns or raises the next scripted outcome for each input key."""

    def __init__(self, scripts: dict):
        self.scripts = scripts
        self.calls: dict[str, int] = {}

    def _next(self, key: str):
        attempt = self.calls.get(key, 0)
        self.calls[key] = attempt + 1
        script = self.scripts[key]
        outcome = script[attempt] if attempt < len(script) else script[-1]
        if callable(outcome):
            outcome = outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def invoke(self, input, config=None, **kwargs):
        return self._next(input)

    async def ainvoke(self, input, config=None, **kwargs):
        return self._next(input)


def _fast_retry(runnable: Runnable) -> Runnable:
    retried = _with_connection_retry(runnable)
    retried.exponential_jitter_params = {
        "initial": 0,
        "max": 0,
        "exp_base": 1,
        "jitter": 0,
    }
    return retried


def _assert_per_index(results, expected):
    assert len(results) == len(expected)
    for actual, wanted in zip(results, expected):
        if isinstance(wanted, type) and issubclass(wanted, BaseException):
            assert isinstance(actual, wanted)
        else:
            assert actual == wanted


async def _run_batch(runnable, inputs, mode: str):
    if mode == "abatch":
        return await runnable.abatch(
            inputs,
            config={"max_concurrency": 4},
            return_exceptions=True,
        )
    return runnable.batch(
        inputs,
        config={"max_concurrency": 4},
        return_exceptions=True,
    )


@pytest.mark.parametrize("mode", ["batch", "abatch"])
@pytest.mark.asyncio
async def test_mixed_batch_keeps_per_index_results(mode):
    # a succeeds only on the 5th try, b always fails the connection, c is a
    # parse error, d succeeds immediately. RunnableRetry's own batch would
    # return ['A', 'A', ValueError, 'D'] or collapse the ValueError.
    scripted = _Scripted(
        {
            "a": [_connection_error, _connection_error, _connection_error, _connection_error, "A"],
            "b": [_connection_error],
            "c": [lambda: ValueError("parse")],
            "d": ["D"],
        }
    )
    retry = _fast_retry(scripted)

    results = await _run_batch(retry, ["a", "b", "c", "d"], mode)

    _assert_per_index(results, ["A", openai.APIConnectionError, ValueError, "D"])
    assert scripted.calls == {"a": 5, "b": 5, "c": 1, "d": 1}


@pytest.mark.parametrize("mode", ["batch", "abatch"])
@pytest.mark.asyncio
async def test_mixed_batch_through_fallbacks_keeps_per_index_results(mode):
    primary_script = _Scripted(
        {
            "a": [_connection_error, _connection_error, _connection_error, _connection_error, "A"],
            "b": [_server_error],
            "c": [lambda: ValueError("parse")],
        }
    )
    fallback_script = _Scripted({"b": ["B-from-fallback"]})
    model = _fast_retry(primary_script).with_fallbacks(
        [_fast_retry(fallback_script)],
        exceptions_to_handle=(openai.APIStatusError,),
    )

    results = await _run_batch(model, ["a", "b", "c"], mode)

    _assert_per_index(results, ["A", "B-from-fallback", ValueError])
    assert primary_script.calls == {"a": 5, "b": 5, "c": 1}
    assert fallback_script.calls == {"b": 1}


@pytest.mark.asyncio
async def test_abatch_honors_max_concurrency():
    state = {"current": 0, "peak": 0}

    class Slow(Runnable):
        def invoke(self, input, config=None, **kwargs):
            return input

        async def ainvoke(self, input, config=None, **kwargs):
            state["current"] += 1
            state["peak"] = max(state["peak"], state["current"])
            await asyncio.sleep(0.05)
            state["current"] -= 1
            return input

    retry = _fast_retry(Slow())
    results = await retry.abatch(
        ["a", "b", "c", "d"],
        config={"max_concurrency": 2},
        return_exceptions=True,
    )

    assert results == ["a", "b", "c", "d"]
    assert state["peak"] <= 2
    assert state["peak"] > 1
