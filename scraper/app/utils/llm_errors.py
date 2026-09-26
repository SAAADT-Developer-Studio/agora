import logging
from collections.abc import Sequence


def format_llm_error(exc: object) -> str:
    if isinstance(exc, BaseException):
        return (
            f"type={type(exc).__name__} "
            f"status_code={getattr(exc, 'status_code', None)} "
            f"error={exc!s} "
            f"cause={exc.__cause__!r}"
        )
    return f"type={type(exc).__name__} status_code=None error={exc!s} cause=None"


def unique_llm_errors(failures: Sequence[object]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    order: list[str] = []
    for failure in failures:
        key = format_llm_error(failure)
        if key not in counts:
            order.append(key)
            counts[key] = 0
        counts[key] += 1
    return [(key, counts[key]) for key in order]


def log_llm_exceptions(prefix: str, failures: Sequence[object]) -> None:
    if not failures:
        return
    for formatted, n in unique_llm_errors(failures):
        logging.warning("%s (%dx): %s", prefix, n, formatted)
