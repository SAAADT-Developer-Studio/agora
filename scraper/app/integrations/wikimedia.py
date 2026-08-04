from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Sequence
from urllib.parse import quote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


WIKIPEDIA_API_URL = "https://sl.wikipedia.org/w/api.php"
WIKIMEDIA_COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
WIKIPEDIA_ARTICLE_URL = "https://sl.wikipedia.org/wiki/"
WIKIMEDIA_USER_AGENT = "VidikWikiImageBot/1.0 (https://vidik.si)"

DEFAULT_MAX_IMAGES_PER_CLUSTER = 1
DEFAULT_SEARCH_RESULTS_PER_CLUSTER = 5
COMMONS_BATCH_SIZE = 20
MAX_RETRIES = 3
MAX_INLINE_RETRY_DELAY_SECONDS = 10.0

EXT_METADATA_FIELDS = "|".join(
    (
        "ImageDescription",
        "ObjectName",
        "Artist",
        "Credit",
        "Attribution",
        "AttributionRequired",
        "License",
        "LicenseShortName",
        "LicenseUrl",
        "UsageTerms",
        "Copyrighted",
        "NonFree",
        "Restrictions",
        "DeletionReason",
    )
)

ALLOWED_LICENSE_NAMES = {
    "cc0",
    "cc0 1.0",
    "public domain",
    *(f"cc by {version}" for version in ("1.0", "2.0", "2.5", "3.0", "4.0")),
    *(f"cc by-sa {version}" for version in ("1.0", "2.0", "2.5", "3.0", "4.0")),
}


@dataclass(frozen=True, slots=True)
class WikimediaImage:
    """A Commons image and the metadata needed for compliant reuse."""

    url: str
    original_url: str
    source_url: str
    file_title: str
    wikipedia_page_title: str
    wikipedia_page_url: str
    artist: str | None
    artist_url: str | None
    attribution_url: str | None
    credit: str | None
    attribution: str
    license: str
    license_url: str | None
    attribution_required: bool
    commons_page_revision_id: int | None
    image_timestamp: str | None
    sha1: str | None
    retrieved_at: str

    def to_metadata(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _WikipediaImageCandidate:
    file_title: str
    wikipedia_page_title: str


@dataclass(frozen=True, slots=True)
class _CommonsImage:
    url: str
    original_url: str
    source_url: str
    file_title: str
    artist: str | None
    artist_url: str | None
    attribution_url: str | None
    credit: str | None
    attribution: str
    license: str
    license_url: str | None
    attribution_required: bool
    commons_page_revision_id: int | None
    image_timestamp: str | None
    sha1: str | None


@dataclass(frozen=True, slots=True)
class WikimediaLookupResult:
    """Images plus whether Wikimedia completed this cluster lookup successfully."""

    images: list[WikimediaImage]
    completed: bool


class WikimediaAPIError(RuntimeError):
    """Raised when Wikimedia returns an API-level error response."""


class WikimediaDeferredError(WikimediaAPIError):
    """Raised when Wikimedia asks the client to stop requesting until a later run."""


def _normalise_file_title(title: str) -> str:
    title = title.replace("_", " ").strip()
    if not title.casefold().startswith("file:"):
        title = f"File:{title}"
    return " ".join(title.split()).casefold()


def _plain_text(value: str | None) -> str | None:
    if not value:
        return None
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return " ".join(text.split()) or None


def _plain_text_and_link(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None

    document = BeautifulSoup(value, "html.parser")
    text = " ".join(document.get_text(" ", strip=True).split()) or None
    link = document.find("a", href=True)
    if link is None:
        return text, None

    href = link.get("href")
    if not isinstance(href, str):
        return text, None
    absolute_url = urljoin("https://commons.wikimedia.org/", href)
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"}:
        return text, None
    return text, absolute_url


def _metadata_raw_value(metadata: dict[str, Any], key: str) -> Any:
    item = metadata.get(key)
    if isinstance(item, dict):
        return item.get("value")
    return item


def _metadata_value(metadata: dict[str, Any], key: str) -> str | None:
    value = _metadata_raw_value(metadata, key)
    return value if isinstance(value, str) else None


def _metadata_is_true(metadata: dict[str, Any], key: str) -> bool:
    value = _metadata_raw_value(metadata, key)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no"}
    return value is not None


def _metadata_is_explicitly_false(metadata: dict[str, Any], key: str) -> bool:
    value = _metadata_raw_value(metadata, key)
    if value is False or value == 0:
        return True
    return isinstance(value, str) and value.strip().casefold() in {"0", "false", "no"}


def _metadata_has_content(metadata: dict[str, Any], key: str) -> bool:
    value = _metadata_raw_value(metadata, key)
    if value is None or value is False or value == 0:
        return False
    if isinstance(value, str):
        return bool(_plain_text(value))
    return True


def _normalise_license_name(value: str | None) -> str:
    return " ".join((value or "").replace("–", "-").split()).casefold()


def _canonical_license_url(license_name: str, license_url: str | None) -> str | None:
    if not license_url:
        return None

    parsed = urlparse(license_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "creativecommons.org",
        "www.creativecommons.org",
    }:
        return None
    path = parsed.path.casefold().rstrip("/")

    if license_name in {"cc0", "cc0 1.0"}:
        expected_path = "/publicdomain/zero/1.0"
        if path != expected_path and not path.startswith(f"{expected_path}/"):
            return None
        return "https://creativecommons.org/publicdomain/zero/1.0/"

    if license_name == "public domain":
        expected_path = "/publicdomain/mark/1.0"
        if path != expected_path and not path.startswith(f"{expected_path}/"):
            return None
        return "https://creativecommons.org/publicdomain/mark/1.0/"

    match = re.fullmatch(r"cc (by|by-sa) (1\.0|2\.0|2\.5|3\.0|4\.0)", license_name)
    if not match:
        return None

    family, version = match.groups()
    expected_path = f"/licenses/{family}/{version}"
    if path != expected_path and not path.startswith(f"{expected_path}/"):
        return None
    return f"https://creativecommons.org{expected_path}/"


def _is_allowed_license(license_name: str | None, license_url: str | None) -> bool:
    normalised_name = _normalise_license_name(license_name)
    if normalised_name not in ALLOWED_LICENSE_NAMES:
        return False
    return _canonical_license_url(normalised_name, license_url) is not None


def _query_pages(data: dict[str, Any]) -> list[dict[str, Any]]:
    pages = data.get("query", {}).get("pages", [])
    if isinstance(pages, list):
        return [page for page in pages if isinstance(page, dict)]
    if isinstance(pages, dict):
        return [page for page in pages.values() if isinstance(page, dict)]
    return []


def _retry_delay(response: httpx.Response | None, attempt: int, api_error: dict | None) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return max((retry_at - datetime.now(timezone.utc)).total_seconds(), 0.0)
                except (TypeError, ValueError, OverflowError):
                    pass

    if api_error is not None:
        lag = api_error.get("lag")
        if isinstance(lag, (int, float)):
            return max(float(lag), 0.0)

    return min(float(2**attempt), MAX_INLINE_RETRY_DELAY_SECONDS)


async def _wait_before_retry(
    response: httpx.Response | None, attempt: int, api_error: dict | None
) -> None:
    delay = _retry_delay(response, attempt, api_error)
    if delay > MAX_INLINE_RETRY_DELAY_SECONDS:
        raise WikimediaDeferredError(
            f"Wikimedia requested a {delay:g}s delay; deferring lookup to a later run"
        )
    await asyncio.sleep(delay)


async def _get_json(
    client: httpx.AsyncClient, url: str, params: dict[str, str | int]
) -> dict[str, Any]:
    for attempt in range(MAX_RETRIES):
        try:
            response = await client.get(url, params=params)
        except httpx.TransportError:
            if attempt == MAX_RETRIES - 1:
                raise
            await _wait_before_retry(None, attempt, None)
            continue

        if response.status_code in {429, 500, 502, 503, 504}:
            if attempt == MAX_RETRIES - 1:
                if response.status_code in {429, 503}:
                    raise WikimediaDeferredError(
                        f"Wikimedia returned HTTP {response.status_code}; deferring batch"
                    )
                response.raise_for_status()
            await _wait_before_retry(response, attempt, None)
            continue

        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise WikimediaAPIError("Wikimedia returned a non-object JSON response")

        error = data.get("error")
        if not isinstance(error, dict):
            return data

        error_code = str(error.get("code", "unknown"))
        if error_code in {"maxlag", "ratelimited"} and attempt < MAX_RETRIES - 1:
            await _wait_before_retry(response, attempt, error)
            continue
        if error_code in {"maxlag", "ratelimited"}:
            raise WikimediaDeferredError(
                f"Wikimedia API returned {error_code}; deferring batch"
            )
        raise WikimediaAPIError(f"Wikimedia API error: {error_code}")

    raise WikimediaAPIError("Wikimedia request exhausted all retries")


def _is_commons_original_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "upload.wikimedia.org"
        and parsed.path.startswith("/wikipedia/commons/")
    )


def _canonical_commons_image_url(value: str) -> str:
    return urlparse(value)._replace(query="", fragment="").geturl()


def _normalise_words(value: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.findall(r"[a-z0-9]+", without_accents)


def _words_match(page_word: str, cluster_word: str) -> bool:
    if page_word == cluster_word:
        return True
    # This tolerates common Slovene inflections (for example Ljubljana/Ljubljani) while
    # still requiring the candidate page to share a distinctive stem with the cluster.
    return (
        len(page_word) >= 6
        and len(cluster_word) >= 6
        and page_word[:5] == cluster_word[:5]
    )


def _is_relevant_wikipedia_page(cluster_title: str, page_title: str) -> bool:
    page_title_without_disambiguation = page_title.split(" (", 1)[0]
    cluster_words = _normalise_words(cluster_title)
    page_words = [
        word
        for word in _normalise_words(page_title_without_disambiguation)
        if len(word) >= 4
    ]
    if not page_words or not cluster_words:
        return False
    matches = [
        any(_words_match(page_word, cluster_word) for cluster_word in cluster_words)
        for page_word in page_words
    ]
    return sum(matches) * 2 >= len(page_words) or matches[0]


async def _search_wikipedia_image_candidates(
    client: httpx.AsyncClient, title: str, search_limit: int
) -> list[_WikipediaImageCandidate]:
    data = await _get_json(
        client,
        WIKIPEDIA_API_URL,
        {
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "generator": "search",
            "gsrsearch": title,
            "gsrnamespace": 0,
            "gsrlimit": search_limit,
            "gsrwhat": "text",
            "gsrsort": "relevance",
            "prop": "pageimages",
            "piprop": "name|original",
            "pilicense": "free",
            "pilimit": search_limit,
            "maxlag": 5,
        },
    )

    candidates: list[_WikipediaImageCandidate] = []
    seen_files: set[str] = set()
    pages = sorted(_query_pages(data), key=lambda page: page.get("index", float("inf")))
    for page in pages:
        file_name = page.get("pageimage")
        page_title = page.get("title")
        original = page.get("original")
        original_url = original.get("source") if isinstance(original, dict) else None
        if (
            not isinstance(file_name, str)
            or not isinstance(page_title, str)
            or not _is_commons_original_url(original_url)
            or not _is_relevant_wikipedia_page(title, page_title)
        ):
            continue
        file_title = (
            file_name if file_name.casefold().startswith("file:") else f"File:{file_name}"
        )
        normalised_title = _normalise_file_title(file_title)
        if normalised_title in seen_files:
            continue
        seen_files.add(normalised_title)
        candidates.append(
            _WikipediaImageCandidate(
                file_title=file_title,
                wikipedia_page_title=page_title,
            )
        )
    return candidates


def _build_attribution(
    metadata: dict[str, Any],
    artist: str | None,
    artist_url: str | None,
    license_name: str,
) -> tuple[str | None, str, str | None, bool]:
    credit, credit_url = _plain_text_and_link(_metadata_value(metadata, "Credit"))
    requested_attribution, requested_attribution_url = _plain_text_and_link(
        _metadata_value(metadata, "Attribution")
    )
    attribution_name = requested_attribution or artist or credit or "Unknown creator"
    attribution_url = (
        requested_attribution_url
        if requested_attribution
        else artist_url if artist else credit_url
    )
    generic_values = {
        "anonymous",
        "own work",
        "self-photographed",
        "unknown",
        "unknown author",
        "unknown creator",
    }
    creator_identified = any(
        value and value.casefold() not in generic_values
        for value in (requested_attribution, artist, credit)
    )
    return (
        credit,
        f"{attribution_name} / Wikimedia Commons / {license_name}",
        attribution_url,
        creator_identified,
    )


def _parse_commons_image(page: dict[str, Any]) -> _CommonsImage | None:
    if page.get("missing") is not None:
        return None

    image_info_list = page.get("imageinfo")
    if not isinstance(image_info_list, list) or not image_info_list:
        return None
    image_info = image_info_list[0]
    if not isinstance(image_info, dict):
        return None

    mime = image_info.get("mime")
    if not isinstance(mime, str) or not mime.startswith("image/"):
        return None

    metadata = image_info.get("extmetadata")
    if not isinstance(metadata, dict):
        return None
    if _metadata_is_true(metadata, "NonFree"):
        return None
    if _metadata_has_content(metadata, "DeletionReason"):
        return None
    if _metadata_has_content(metadata, "Restrictions"):
        return None

    license_name = _metadata_value(metadata, "LicenseShortName") or _metadata_value(
        metadata, "UsageTerms"
    )
    license_url = _metadata_value(metadata, "LicenseUrl")
    normalised_license_name = _normalise_license_name(license_name)
    if not license_name or normalised_license_name not in ALLOWED_LICENSE_NAMES:
        return None
    license_url = _canonical_license_url(normalised_license_name, license_url)
    if normalised_license_name == "public domain" and not _metadata_is_explicitly_false(
        metadata, "Copyrighted"
    ):
        return None
    if normalised_license_name != "public domain" and license_url is None:
        return None

    url = image_info.get("thumburl") or image_info.get("url")
    original_url = image_info.get("url")
    source_url = image_info.get("descriptionurl")
    file_title = page.get("title")
    required_values = (url, original_url, source_url, file_title)
    if not all(isinstance(value, str) and value for value in required_values):
        return None
    if not _is_commons_original_url(url) or not _is_commons_original_url(original_url):
        return None
    url = _canonical_commons_image_url(url)
    original_url = _canonical_commons_image_url(original_url)
    parsed_source_url = urlparse(source_url)
    if (
        parsed_source_url.scheme != "https"
        or parsed_source_url.hostname != "commons.wikimedia.org"
    ):
        return None

    artist, artist_url = _plain_text_and_link(_metadata_value(metadata, "Artist"))
    credit, attribution, attribution_url, creator_identified = _build_attribution(
        metadata, artist, artist_url, license_name
    )
    attribution_required = _metadata_is_true(metadata, "AttributionRequired") or (
        normalised_license_name not in {"cc0", "cc0 1.0", "public domain"}
    )
    if attribution_required and not creator_identified:
        return None

    return _CommonsImage(
        url=url,
        original_url=original_url,
        source_url=source_url,
        file_title=file_title,
        artist=artist,
        artist_url=artist_url,
        attribution_url=attribution_url,
        credit=credit,
        attribution=attribution,
        license=license_name,
        license_url=license_url,
        attribution_required=attribution_required,
        commons_page_revision_id=(
            page.get("lastrevid") if isinstance(page.get("lastrevid"), int) else None
        ),
        image_timestamp=(
            image_info.get("timestamp") if isinstance(image_info.get("timestamp"), str) else None
        ),
        sha1=image_info.get("sha1") if isinstance(image_info.get("sha1"), str) else None,
    )


async def _fetch_commons_images(
    client: httpx.AsyncClient, file_titles: Sequence[str]
) -> tuple[dict[str, _CommonsImage], set[str]]:
    images: dict[str, _CommonsImage] = {}
    failed_file_titles: set[str] = set()
    for offset in range(0, len(file_titles), COMMONS_BATCH_SIZE):
        batch = file_titles[offset : offset + COMMONS_BATCH_SIZE]
        try:
            data = await _get_json(
                client,
                WIKIMEDIA_COMMONS_API_URL,
                {
                    "action": "query",
                    "format": "json",
                    "formatversion": 2,
                    "redirects": 1,
                    "titles": "|".join(batch),
                    "prop": "imageinfo|info",
                    "iiprop": "url|mime|size|timestamp|sha1|extmetadata",
                    "iiurlwidth": 1200,
                    "iilimit": 1,
                    "iimetadataversion": "latest",
                    "iiextmetadatalanguage": "en",
                    "iiextmetadatafilter": EXT_METADATA_FIELDS,
                    "maxlag": 5,
                },
            )
        except WikimediaDeferredError:
            raise
        except (httpx.HTTPError, ValueError, WikimediaAPIError) as error:
            logging.warning(
                "Failed to retrieve Wikimedia Commons metadata batch %d: %s",
                offset // COMMONS_BATCH_SIZE + 1,
                error,
            )
            failed_file_titles.update(_normalise_file_title(title) for title in batch)
            continue

        batch_images: dict[str, _CommonsImage] = {}
        for page in _query_pages(data):
            image = _parse_commons_image(page)
            if image is not None:
                batch_images[_normalise_file_title(image.file_title)] = image
        images.update(batch_images)

        query = data.get("query", {})
        aliases: list[dict[str, Any]] = []
        for key in ("normalized", "redirects"):
            values = query.get(key, []) if isinstance(query, dict) else []
            if isinstance(values, list):
                aliases.extend(value for value in values if isinstance(value, dict))
        for alias in aliases:
            source = alias.get("from")
            destination = alias.get("to")
            if not isinstance(source, str) or not isinstance(destination, str):
                continue
            image = images.get(_normalise_file_title(destination))
            if image is not None:
                images[_normalise_file_title(source)] = image

    return images, failed_file_titles


def _chunk_unique_file_titles(
    candidates_by_title: dict[str, list[_WikipediaImageCandidate]],
) -> list[str]:
    file_titles: list[str] = []
    seen: set[str] = set()
    for candidates in candidates_by_title.values():
        for candidate in candidates:
            key = _normalise_file_title(candidate.file_title)
            if key not in seen:
                seen.add(key)
                file_titles.append(candidate.file_title)
    return file_titles


async def _find_wikimedia_images(
    client: httpx.AsyncClient,
    cluster_titles: Sequence[str],
    max_images_per_cluster: int,
    search_results_per_cluster: int,
) -> list[WikimediaLookupResult]:
    unique_titles = list(dict.fromkeys(title.strip() for title in cluster_titles if title.strip()))
    candidates_by_title: dict[str, list[_WikipediaImageCandidate]] = {}
    search_completed_by_title: dict[str, bool] = {}

    # Wikimedia asks automated clients to make API requests serially. Results are persisted and
    # reused for unchanged clusters, so this path normally runs only for newly created clusters.
    for title in unique_titles:
        try:
            candidates_by_title[title] = await _search_wikipedia_image_candidates(
                client, title, search_results_per_cluster
            )
            search_completed_by_title[title] = True
        except WikimediaDeferredError:
            raise
        except (httpx.HTTPError, ValueError, WikimediaAPIError) as error:
            logging.warning("Failed to find Wikipedia image candidates for %r: %s", title, error)
            candidates_by_title[title] = []
            search_completed_by_title[title] = False

    file_titles = _chunk_unique_file_titles(candidates_by_title)
    try:
        commons_images, failed_file_titles = await _fetch_commons_images(client, file_titles)
    except WikimediaDeferredError:
        raise
    except (httpx.HTTPError, ValueError, WikimediaAPIError) as error:
        logging.warning("Failed to retrieve Wikimedia Commons image metadata: %s", error)
        commons_images = {}
        failed_file_titles = {
            _normalise_file_title(file_title) for file_title in file_titles
        }

    retrieved_at = datetime.now(timezone.utc).isoformat()
    results_by_title: dict[str, WikimediaLookupResult] = {}
    for title, candidates in candidates_by_title.items():
        images: list[WikimediaImage] = []
        seen_urls: set[str] = set()
        for candidate in candidates:
            commons_image = commons_images.get(_normalise_file_title(candidate.file_title))
            if commons_image is None or commons_image.url in seen_urls:
                continue
            seen_urls.add(commons_image.url)
            page_slug = quote(candidate.wikipedia_page_title.replace(" ", "_"), safe="")
            images.append(
                WikimediaImage(
                    **asdict(commons_image),
                    wikipedia_page_title=candidate.wikipedia_page_title,
                    wikipedia_page_url=f"{WIKIPEDIA_ARTICLE_URL}{page_slug}",
                    retrieved_at=retrieved_at,
                )
            )
            if len(images) >= max_images_per_cluster:
                break
        commons_lookup_completed = not any(
            _normalise_file_title(candidate.file_title) in failed_file_titles
            for candidate in candidates
        )
        results_by_title[title] = WikimediaLookupResult(
            images=images,
            completed=search_completed_by_title[title]
            and (bool(images) or commons_lookup_completed),
        )

    return [
        results_by_title.get(
            title.strip(),
            WikimediaLookupResult(images=[], completed=not bool(title.strip())),
        )
        for title in cluster_titles
    ]


async def lookup_wikimedia_images_for_clusters(
    cluster_titles: Sequence[str],
    *,
    max_images_per_cluster: int = DEFAULT_MAX_IMAGES_PER_CLUSTER,
    search_results_per_cluster: int = DEFAULT_SEARCH_RESULTS_PER_CLUSTER,
    client: httpx.AsyncClient | None = None,
) -> list[WikimediaLookupResult]:
    """Look up reusable Commons images associated with Slovene Wikipedia results.

    The returned list matches ``cluster_titles`` in length and order. ``completed`` distinguishes
    a valid no-match from a transient failure so callers can safely persist negative results.
    """

    if max_images_per_cluster < 1:
        raise ValueError("max_images_per_cluster must be at least 1")
    if search_results_per_cluster < max_images_per_cluster:
        raise ValueError("search_results_per_cluster must be at least max_images_per_cluster")

    if client is not None:
        return await _find_wikimedia_images(
            client,
            cluster_titles,
            max_images_per_cluster,
            search_results_per_cluster,
        )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(5.0),
        follow_redirects=True,
        headers={
            "User-Agent": WIKIMEDIA_USER_AGENT,
            "Accept": "application/json",
        },
    ) as owned_client:
        return await _find_wikimedia_images(
            owned_client,
            cluster_titles,
            max_images_per_cluster,
            search_results_per_cluster,
        )


async def find_wikimedia_images_for_clusters(
    cluster_titles: Sequence[str],
    *,
    max_images_per_cluster: int = DEFAULT_MAX_IMAGES_PER_CLUSTER,
    search_results_per_cluster: int = DEFAULT_SEARCH_RESULTS_PER_CLUSTER,
    client: httpx.AsyncClient | None = None,
) -> list[list[WikimediaImage]]:
    """Return image lists while retaining the simple public interface used by callers/tests."""

    results = await lookup_wikimedia_images_for_clusters(
        cluster_titles,
        max_images_per_cluster=max_images_per_cluster,
        search_results_per_cluster=search_results_per_cluster,
        client=client,
    )
    return [result.images for result in results]
