import httpx
import pytest

import app.integrations.wikimedia as wikimedia
from app.integrations.wikimedia import (
    WIKIMEDIA_COMMONS_API_URL,
    WIKIPEDIA_API_URL,
    _get_json,
    _is_allowed_license,
    _is_relevant_wikipedia_page,
    _parse_commons_image,
    find_wikimedia_images_for_clusters,
    lookup_wikimedia_images_for_clusters,
)


def _metadata(value: str) -> dict[str, str]:
    return {"value": value}


class TestWikimediaLicenses:
    @pytest.mark.parametrize(
        ("name", "url"),
        [
            ("CC0", "https://creativecommons.org/publicdomain/zero/1.0/"),
            ("Public domain", "https://creativecommons.org/publicdomain/mark/1.0/"),
            ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"),
            ("CC BY-SA 3.0", "https://creativecommons.org/licenses/by-sa/3.0/"),
            ("CC0", "http://creativecommons.org/publicdomain/zero/1.0/deed.en"),
        ],
    )
    def test_accepts_supported_reuse_licenses(self, name: str, url: str):
        assert _is_allowed_license(name, url)

    @pytest.mark.parametrize(
        ("name", "url"),
        [
            ("CC BY-NC 4.0", "https://creativecommons.org/licenses/by-nc/4.0/"),
            ("CC BY-ND 4.0", "https://creativecommons.org/licenses/by-nd/4.0/"),
            ("GFDL", "https://www.gnu.org/licenses/fdl-1.3.html"),
            ("CC BY 4.0", "https://creativecommons.org/licenses/by-nc/4.0/"),
            ("CC BY 4.0", "https://example.invalid/licenses/by/4.0/"),
            ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0-fake/"),
            ("CC0", None),
            ("Public domain", None),
            ("Unknown", None),
        ],
    )
    def test_rejects_unsupported_or_mismatched_licenses(self, name: str, url: str | None):
        assert not _is_allowed_license(name, url)


@pytest.mark.asyncio
async def test_finds_commons_images_and_keeps_attribution_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(WIKIPEDIA_API_URL):
            assert request.url.params["pilicense"] == "free"
            assert request.url.params["piprop"] == "name|original"
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {
                                "pageid": 1,
                                "ns": 0,
                                "title": "Ljubljana",
                                "index": 1,
                                "pageimage": "Ljubljana.jpg",
                                "original": {
                                    "source": (
                                        "https://upload.wikimedia.org/wikipedia/commons/a/ab/"
                                        "Ljubljana.jpg"
                                    )
                                },
                            },
                            {
                                "pageid": 2,
                                "ns": 0,
                                "title": "Local file",
                                "index": 2,
                                "pageimage": "Local.jpg",
                                "original": {
                                    "source": (
                                        "https://upload.wikimedia.org/wikipedia/sl/a/ab/Local.jpg"
                                    )
                                },
                            },
                            {
                                "pageid": 3,
                                "ns": 0,
                                "title": "Ljubljana",
                                "index": 3,
                                "pageimage": "Restricted.jpg",
                                "original": {
                                    "source": (
                                        "https://upload.wikimedia.org/wikipedia/commons/c/cd/"
                                        "Restricted.jpg"
                                    )
                                },
                            },
                        ]
                    }
                },
            )

        assert str(request.url).startswith(WIKIMEDIA_COMMONS_API_URL)
        assert "File:Local.jpg" not in request.url.params["titles"]
        assert request.url.params["prop"] == "imageinfo|info"
        assert request.url.params["iiprop"] == (
            "url|mime|size|timestamp|sha1|extmetadata"
        )
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 10,
                            "lastrevid": 123,
                            "title": "File:Ljubljana.jpg",
                            "imagerepository": "local",
                            "imageinfo": [
                                {
                                    "url": (
                                        "https://upload.wikimedia.org/wikipedia/commons/a/ab/"
                                        "Ljubljana.jpg"
                                    ),
                                    "timestamp": "2026-08-04T10:00:00Z",
                                    "sha1": "0123456789abcdef",
                                    "thumburl": (
                                        "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/"
                                        "Ljubljana.jpg/1200px-Ljubljana.jpg?utm_source=commons"
                                    ),
                                    "descriptionurl": (
                                        "https://commons.wikimedia.org/wiki/File:Ljubljana.jpg"
                                    ),
                                    "mime": "image/jpeg",
                                    "extmetadata": {
                                        "Artist": _metadata(
                                            '<a href="/wiki/User:Jane">Jane Photographer</a>'
                                        ),
                                        "Credit": _metadata("Own work"),
                                        "AttributionRequired": _metadata("true"),
                                        "LicenseShortName": _metadata("CC BY 4.0"),
                                        "LicenseUrl": _metadata(
                                            "http://creativecommons.org/licenses/by/4.0/deed.en"
                                        ),
                                    },
                                }
                            ],
                        },
                        {
                            "pageid": 11,
                            "lastrevid": 456,
                            "title": "File:Restricted.jpg",
                            "imagerepository": "local",
                            "imageinfo": [
                                {
                                    "url": "https://upload.wikimedia.org/restricted.jpg",
                                    "descriptionurl": (
                                        "https://commons.wikimedia.org/wiki/File:Restricted.jpg"
                                    ),
                                    "mime": "image/jpeg",
                                    "extmetadata": {
                                        "Restrictions": _metadata("personality rights"),
                                        "LicenseShortName": _metadata("CC BY 4.0"),
                                        "LicenseUrl": _metadata(
                                            "https://creativecommons.org/licenses/by/4.0/"
                                        ),
                                    },
                                }
                            ],
                        },
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await find_wikimedia_images_for_clusters(
            ["Ljubljana"],
            client=client,
        )

    assert len(results) == 1
    assert len(results[0]) == 1
    image = results[0][0]
    assert image.file_title == "File:Ljubljana.jpg"
    assert image.artist == "Jane Photographer"
    assert image.artist_url == "https://commons.wikimedia.org/wiki/User:Jane"
    assert image.attribution_url == image.artist_url
    assert image.license == "CC BY 4.0"
    assert image.license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert image.attribution == "Jane Photographer / Wikimedia Commons / CC BY 4.0"
    assert image.wikipedia_page_title == "Ljubljana"
    assert image.wikipedia_page_url == "https://sl.wikipedia.org/wiki/Ljubljana"
    assert image.url.endswith("1200px-Ljubljana.jpg")
    assert image.commons_page_revision_id == 123
    assert image.image_timestamp == "2026-08-04T10:00:00Z"
    assert image.sha1 == "0123456789abcdef"
    assert image.to_metadata()["source_url"] == image.source_url


@pytest.mark.asyncio
async def test_network_failure_returns_empty_result_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, headers={"Retry-After": "0"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await lookup_wikimedia_images_for_clusters(["Unavailable"], client=client)

    assert results[0].images == []
    assert not results[0].completed


@pytest.mark.asyncio
async def test_retries_transient_server_failure():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(502, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json={"query": {"pages": []}}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _get_json(client, WIKIPEDIA_API_URL, {"action": "query"})

    assert result == {"query": {"pages": []}}
    assert attempts == 2


@pytest.mark.asyncio
async def test_defers_instead_of_ignoring_long_retry_after():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "60"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(wikimedia.WikimediaAPIError, match="deferring lookup"):
            await _get_json(client, WIKIPEDIA_API_URL, {"action": "query"})

    assert attempts == 1


@pytest.mark.asyncio
async def test_long_retry_after_stops_the_entire_cluster_batch():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "60"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(wikimedia.WikimediaDeferredError):
            await find_wikimedia_images_for_clusters(["First", "Second"], client=client)

    assert attempts == 1


@pytest.mark.asyncio
async def test_skips_search_results_unrelated_to_cluster_title():
    commons_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal commons_requests
        if str(request.url).startswith(WIKIPEDIA_API_URL):
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {
                                "title": "Unrelated person",
                                "pageimage": "Person.jpg",
                                "original": {
                                    "source": (
                                        "https://upload.wikimedia.org/wikipedia/commons/a/ab/"
                                        "Person.jpg"
                                    )
                                },
                            }
                        ]
                    }
                },
            )
        commons_requests += 1
        return httpx.Response(200, json={"query": {"pages": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await find_wikimedia_images_for_clusters(["Ljubljana"], client=client)

    assert results == [[]]
    assert commons_requests == 0


@pytest.mark.asyncio
async def test_keeps_successful_commons_batches_when_a_later_batch_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    calls = 0

    async def fake_get_json(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise wikimedia.WikimediaAPIError("temporary failure")
        return {
            "query": {
                "pages": [
                    {
                        "title": "File:First.jpg",
                        "imageinfo": [
                            {
                                "url": (
                                    "https://upload.wikimedia.org/wikipedia/commons/a/ab/"
                                    "First.jpg"
                                ),
                                "descriptionurl": (
                                    "https://commons.wikimedia.org/wiki/File:First.jpg"
                                ),
                                "mime": "image/jpeg",
                                "extmetadata": {
                                    "Artist": _metadata("Creator"),
                                    "LicenseShortName": _metadata("CC0"),
                                    "LicenseUrl": _metadata(
                                        "https://creativecommons.org/publicdomain/zero/1.0/"
                                    ),
                                },
                            }
                        ],
                    }
                ]
            }
        }

    monkeypatch.setattr(wikimedia, "COMMONS_BATCH_SIZE", 1)
    monkeypatch.setattr(wikimedia, "_get_json", fake_get_json)

    async with httpx.AsyncClient() as client:
        images, failed_file_titles = await wikimedia._fetch_commons_images(
            client, ["File:First.jpg", "File:Second.jpg"]
        )

    assert "file:first.jpg" in images
    assert failed_file_titles == {"file:second.jpg"}
    assert calls == 2


@pytest.mark.parametrize(
    ("cluster_title", "page_title"),
    [
        ("Trump napovedal nove carine", "Donald Trump"),
        ("Golob predstavil zakon", "Robert Golob"),
        ("Dogodek v Novi Gorici", "Nova Gorica"),
        ("Vlada sprejela zakon", "Vlada Republike Slovenije"),
    ],
)
def test_accepts_relevant_named_entity_pages(cluster_title: str, page_title: str):
    assert _is_relevant_wikipedia_page(cluster_title, page_title)


def _parse_test_image(extmetadata: dict[str, object]):
    return _parse_commons_image(
        {
            "title": "File:Test.jpg",
            "lastrevid": 123,
            "imageinfo": [
                {
                    "url": (
                        "https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.jpg"
                    ),
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Test.jpg",
                    "mime": "image/jpeg",
                    "extmetadata": extmetadata,
                }
            ],
        }
    )


def test_rejects_attribution_license_without_identifiable_creator():
    image = _parse_test_image(
        {
            "Credit": _metadata("Own work"),
            "LicenseShortName": _metadata("CC BY 4.0"),
            "LicenseUrl": _metadata("https://creativecommons.org/licenses/by/4.0/"),
        }
    )

    assert image is None


def test_preserves_custom_attribution_link():
    image = _parse_test_image(
        {
            "Attribution": _metadata(
                '<a href="https://example.com/creator">Photo by Example Creator</a>'
            ),
            "LicenseShortName": _metadata("CC BY 4.0"),
            "LicenseUrl": _metadata("https://creativecommons.org/licenses/by/4.0/"),
        }
    )

    assert image is not None
    assert image.attribution.startswith("Photo by Example Creator")
    assert image.attribution_url == "https://example.com/creator"


def test_accepts_public_domain_declaration_without_license_url():
    image = _parse_test_image(
        {
            "Artist": _metadata("Government archive"),
            "Copyrighted": _metadata("False"),
            "LicenseShortName": _metadata("Public domain"),
        }
    )

    assert image is not None
    assert image.license == "Public domain"
    assert image.license_url is None


@pytest.mark.parametrize("copyrighted", ["True", ["unknown"]])
def test_rejects_contradictory_public_domain_metadata(copyrighted: object):
    image = _parse_test_image(
        {
            "Artist": _metadata("Government archive"),
            "Copyrighted": {"value": copyrighted},
            "LicenseShortName": _metadata("Public domain"),
            "LicenseUrl": _metadata(
                "https://creativecommons.org/publicdomain/mark/1.0/"
            ),
        }
    )

    assert image is None


def test_rejects_unexpected_nonfree_metadata_shape():
    image = _parse_test_image(
        {
            "Artist": _metadata("Creator"),
            "NonFree": ["unknown"],
            "LicenseShortName": _metadata("CC0"),
            "LicenseUrl": _metadata(
                "https://creativecommons.org/publicdomain/zero/1.0/"
            ),
        }
    )

    assert image is None
