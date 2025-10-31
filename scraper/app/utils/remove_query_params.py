from urllib.parse import urlparse, urlunparse


def remove_query_params(url: str) -> str:
    """Remove query parameters from a URL."""
    parsed_url = urlparse(url)
    cleaned_url = urlunparse((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", "", ""))
    return cleaned_url
