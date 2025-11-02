import pytest
from app.utils.remove_query_params import remove_query_params


def test_remove_query_params_with_single_param():
    """Test removing query parameters with a single parameter."""
    url = "https://example.com/path?key=value"
    expected = "https://example.com/path"
    assert remove_query_params(url) == expected


def test_remove_query_params_with_multiple_params():
    """Test removing query parameters with multiple parameters."""
    url = "https://example.com/path?key1=value1&key2=value2"
    expected = "https://example.com/path"
    assert remove_query_params(url) == expected


def test_remove_query_params_without_params():
    """Test URL that has no query parameters."""
    url = "https://example.com/path"
    expected = "https://example.com/path"
    assert remove_query_params(url) == expected


def test_remove_query_params_with_fragment():
    """Test removing query parameters while preserving URL structure."""
    url = "https://example.com/path?key=value#fragment"
    expected = "https://example.com/path"
    assert remove_query_params(url) == expected


def test_remove_query_params_with_port():
    """Test removing query parameters from URL with port number."""
    url = "https://example.com:8080/path?key=value"
    expected = "https://example.com:8080/path"
    assert remove_query_params(url) == expected
