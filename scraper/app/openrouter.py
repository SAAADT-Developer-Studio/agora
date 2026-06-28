import logging

from langchain.chat_models import init_chat_model
from openai import PermissionDeniedError, RateLimitError

from app import config


DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"


def create_openrouter_chat_model(model_name: str = DEFAULT_OPENROUTER_MODEL):
    primary_model = init_chat_model(
        model_name,
        model_provider="openai",
        base_url=config.OPENROUTER_BASE_URL,
        api_key=config.OPENROUTER_API_KEY,
    )

    fallback_key = config.OPENROUTER_FALLBACK_API_KEY
    if not fallback_key:
        return primary_model

    fallback_model = init_chat_model(
        model_name,
        model_provider="openai",
        base_url=config.OPENROUTER_BASE_URL,
        api_key=fallback_key,
    )

    logging.info("OpenRouter fallback API key configured")
    return primary_model.with_fallbacks(
        [fallback_model],
        exceptions_to_handle=(RateLimitError, PermissionDeniedError),
    )
