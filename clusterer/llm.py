"""OpenRouter chat call shared by the judge and the summary step."""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

MODEL = "deepseek/deepseek-v4-flash"
_TIMEOUT_SECONDS = 30

# prompt -> JSON content of the reply. The judge and the summary step take one
# of these, so the replay harness can put a cache and a spend cap in between.
Complete = Callable[[str], str]


class MissingKey(Exception):
    pass


@dataclass(frozen=True)
class Reply:
    content: str
    cost_usd: float


def chat(prompt: str, *, response_format: dict, max_tokens: int | None = None) -> Reply:
    """One completion. Retries once on the fallback key when credits run out."""
    primary = os.getenv("OPENROUTER_API_KEY") or None
    if not primary:
        raise MissingKey()
    body: dict = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "reasoning": {"enabled": False},
        "response_format": response_format,
        "usage": {"include": True},
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    try:
        return _post(primary, body)
    except urllib.error.HTTPError as exc:
        fallback = os.getenv("OPENROUTER_FALLBACK_API_KEY") or os.getenv(
            "OPENROUTER_API_KEY_FALLBACK"
        )
        if exc.code == 402 and fallback:
            return _post(fallback, body)
        raise


def _post(api_key: str, body: dict) -> Reply:
    url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    request = urllib.request.Request(
        f"{url}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read())
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError(f"expected string content, got {content!r}")
    usage = payload.get("usage") or {}
    return Reply(content=content, cost_usd=float(usage.get("cost") or 0.0))
