import openai
import pytest
from langchain_core.runnables.fallbacks import RunnableWithFallbacks
from langchain_core.runnables.retry import RunnableRetry

from app import config
from app.openrouter import create_openrouter_chat_model
from app.pipeline.analyzer import ArticleAnalysis

_RETRY_EXCEPTIONS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
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
