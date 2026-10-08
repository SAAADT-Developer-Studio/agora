import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Sequence

from .assign import PromptMember

MODEL = "deepseek/deepseek-v4-flash"
_TIMEOUT_SECONDS = 30

logger = logging.getLogger(__name__)
_missing_key_logged = False


def build_prompt(title: str, summary: str | None, members: Sequence[PromptMember]) -> str:
    lines = [
        "You group Slovenian news into stories.",
        "",
        "A story is one real-world happening. Immediate beats belong in it: the meeting, "
        "quotes from that meeting, the political fallout of that meeting. The same topic "
        "does not: another story about the same war, the same politician, or the same "
        "country in the same week.",
        "",
        "New article:",
        f"Title: {title}",
    ]
    if summary and summary.strip():
        lines.append(f"Summary: {summary}")
    lines.extend(["", "Nearest story:"])
    for index, (member_title, member_summary) in enumerate(members, start=1):
        lines.append(f"{index}. Title: {member_title}")
        if member_summary and member_summary.strip():
            lines.append(f"   Summary: {member_summary}")
    lines.extend(["", "Is the new article the same happening as that story?"])
    return "\n".join(lines)


def parse_same(content: str) -> bool:
    data = json.loads(content)
    same = data.get("same") if isinstance(data, dict) else None
    if not isinstance(same, bool):
        raise ValueError(f"expected {{\"same\": bool}}, got {content!r}")
    return same


def same_happening(title: str, summary: str | None, members: Sequence[PromptMember]) -> bool:
    global _missing_key_logged
    primary = os.getenv("OPENROUTER_API_KEY") or None
    if not primary:
        if not _missing_key_logged:
            logger.warning("OPENROUTER_API_KEY missing; gray-band articles will seed")
            _missing_key_logged = True
        return False
    prompt = build_prompt(title, summary, members)
    try:
        return _complete(primary, prompt)
    except urllib.error.HTTPError as exc:
        fallback = os.getenv("OPENROUTER_FALLBACK_API_KEY") or os.getenv(
            "OPENROUTER_API_KEY_FALLBACK"
        )
        if exc.code == 402 and fallback:
            return _complete(fallback, prompt)
        raise


def _complete(api_key: str, prompt: str) -> bool:
    url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "reasoning": {"enabled": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "same_happening",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"same": {"type": "boolean"}},
                    "required": ["same"],
                    "additionalProperties": False,
                },
            },
        },
    }
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
    return parse_same(content)
