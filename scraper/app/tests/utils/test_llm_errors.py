from app.utils.llm_errors import format_llm_error, unique_llm_errors


class FakeStatusError(Exception):
    def __init__(self, message: str, status_code: int | None):
        super().__init__(message)
        self.status_code = status_code


def test_format_includes_type_status_str_and_cause():
    cause = ConnectionError("timed out")
    exc = FakeStatusError("Connection error.", None)
    exc.__cause__ = cause

    formatted = format_llm_error(exc)

    assert "type=FakeStatusError" in formatted
    assert "status_code=None" in formatted
    assert "error=Connection error." in formatted
    assert "cause=ConnectionError('timed out')" in formatted


def test_format_includes_http_status_code():
    exc = FakeStatusError("Error code: 402 - insufficient credits", 402)

    formatted = format_llm_error(exc)

    assert "type=FakeStatusError" in formatted
    assert "status_code=402" in formatted
    assert "error=Error code: 402 - insufficient credits" in formatted
    assert "cause=None" in formatted


def test_unique_errors_count_repeats_in_first_seen_order():
    first = FakeStatusError("Connection error.", None)
    second = FakeStatusError("Error code: 402 - nope", 402)
    third = FakeStatusError("Connection error.", None)

    unique = unique_llm_errors([first, second, third])

    assert unique == [
        (format_llm_error(first), 2),
        (format_llm_error(second), 1),
    ]
