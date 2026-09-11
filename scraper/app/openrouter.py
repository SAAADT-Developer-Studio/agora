import logging

from langchain.chat_models import init_chat_model
from openai import APIStatusError

from app import config


DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"


def create_openrouter_chat_model(model_name: str = DEFAULT_OPENROUTER_MODEL):
    primary_model = init_chat_model(
        model_name,
        model_provider="openai",
        base_url=config.OPENROUTER_BASE_URL,
        api_key=config.OPENROUTER_API_KEY,
        extra_body={"reasoning": {"enabled": False}},
    )

    fallback_key = config.OPENROUTER_FALLBACK_API_KEY
    if not fallback_key:
        return primary_model

    fallback_model = init_chat_model(
        model_name,
        model_provider="openai",
        base_url=config.OPENROUTER_BASE_URL,
        api_key=fallback_key,
        extra_body={"reasoning": {"enabled": False}},
    )

    logging.info("OpenRouter fallback API key configured")
    return primary_model.with_fallbacks(
        [fallback_model],
        # OpenRouter's 402 credit errors use APIStatusError directly; 403 and
        # 429 errors are subclasses and remain covered by this handler.
        exceptions_to_handle=(APIStatusError,),
    )
