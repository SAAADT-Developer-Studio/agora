import logging
from functools import wraps
from typing import Any, override

import openai
from langchain.chat_models import init_chat_model
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.runnables.retry import RunnableRetry
from openai import APIStatusError

from app import config


DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"

# max_retries=0 disables the SDK retry loop, including its 5xx retries, so
# InternalServerError is listed here. Rate-limit and 5xx errors are
# APIStatusError subclasses: once these attempts are exhausted they still
# fall through to the fallback key. Connection errors are not.
_RETRY_EXCEPTIONS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class _DelegatingRetry(RunnableRetry):
    """RunnableRetry that keeps chat-model helpers on the wrapped model.

    RunnableRetry does not delegate unknown attributes, so
    ``with_structured_output`` raises AttributeError and article analysis would
    call OpenRouter with the SDK retries disabled and no jittered replacement.
    Re-apply this same retry policy to the runnable that helper returns.
    ``with_fallbacks`` then runs the helper for every key.
    """

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        attr = getattr(self.bound, name)
        if name != "with_structured_output":
            return attr

        @wraps(attr)
        def with_structured_output(*args: Any, **kwargs: Any) -> Runnable:
            return _with_connection_retry(attr(*args, **kwargs))

        return with_structured_output

    @override
    def batch(
        self,
        inputs: list[Any],
        config: RunnableConfig | list[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> list[Any]:
        # RunnableRetry.batch retries the whole batch, then zips leftover
        # exceptions back by position. One late success shifts later results,
        # and a retryable error also re-runs inputs that already failed parsing.
        # Runnable.batch calls invoke per input, so each item retries on its own.
        return Runnable.batch(
            self,
            inputs,
            config,
            return_exceptions=return_exceptions,
            **kwargs,
        )

    @override
    async def abatch(
        self,
        inputs: list[Any],
        config: RunnableConfig | list[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> list[Any]:
        return await Runnable.abatch(
            self,
            inputs,
            config,
            return_exceptions=return_exceptions,
            **kwargs,
        )


def _with_connection_retry(model: Runnable) -> _DelegatingRetry:
    retried = model.with_retry(
        retry_if_exception_type=_RETRY_EXCEPTIONS,
        wait_exponential_jitter=True,
        stop_after_attempt=5,
    )
    return _DelegatingRetry(
        bound=retried.bound,
        kwargs=retried.kwargs,
        config=retried.config,
        config_factories=list(retried.config_factories),
        custom_input_type=retried.custom_input_type,
        custom_output_type=retried.custom_output_type,
        retry_exception_types=retried.retry_exception_types,
        wait_exponential_jitter=retried.wait_exponential_jitter,
        exponential_jitter_params=retried.exponential_jitter_params,
        max_attempt_number=retried.max_attempt_number,
    )


def _init_openrouter_model(model_name: str, api_key: str) -> _DelegatingRetry:
    chat = init_chat_model(
        model_name,
        model_provider="openai",
        base_url=config.OPENROUTER_BASE_URL,
        api_key=api_key,
        extra_body={"reasoning": {"enabled": False}},
        max_retries=0,
        timeout=60,
    )
    return _with_connection_retry(chat)


def create_openrouter_chat_model(model_name: str = DEFAULT_OPENROUTER_MODEL):
    primary_model = _init_openrouter_model(model_name, config.OPENROUTER_API_KEY)

    fallback_key = config.OPENROUTER_FALLBACK_API_KEY
    logging.info("OpenRouter fallback key present: %s", bool(fallback_key))
    if not fallback_key:
        return primary_model

    fallback_model = _init_openrouter_model(model_name, fallback_key)
    return primary_model.with_fallbacks(
        [fallback_model],
        # OpenRouter's 402 credit errors use APIStatusError directly; 403 and
        # 429 errors are subclasses and remain covered by this handler.
        exceptions_to_handle=(APIStatusError,),
    )
