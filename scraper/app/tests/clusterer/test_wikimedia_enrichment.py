from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

import app.clusterer.run_clustering as clustering_module
from app.database.schema import ClusterV2


@dataclass
class FakeWikimediaImage:
    url: str

    def to_metadata(self) -> dict[str, object]:
        return {
            "url": self.url,
            "source_url": "https://commons.wikimedia.org/wiki/File:Image.jpg",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution_required": True,
            "attribution": "Creator / Wikimedia Commons / CC BY 4.0",
        }


@dataclass
class FakeLookupResult:
    images: list[FakeWikimediaImage]
    completed: bool = True


def test_cluster_defaults_to_empty_wikimedia_fields():
    cluster = ClusterV2(title="Cluster", slug="cluster", run_id=1)

    assert cluster.wiki_image_urls == []
    assert cluster.wiki_image_metadata == []
    assert cluster.wiki_image_lookup_at is None
    assert cluster.wiki_image_last_attempt_at is None


@pytest.mark.asyncio
async def test_enriches_unresolved_cluster(monkeypatch: pytest.MonkeyPatch):
    async def lookup_images(titles: list[str]):
        assert titles == ["New cluster"]
        return [
            FakeLookupResult(
                [FakeWikimediaImage("https://upload.wikimedia.org/image.jpg")]
            )
        ]

    monkeypatch.setattr(
        clustering_module, "lookup_wikimedia_images_for_clusters", lookup_images
    )
    payloads = [("New cluster", [], [], [], None, None)]

    result = await clustering_module.enrich_cluster_payloads_with_wikimedia(payloads)

    assert result[0][2] == ["https://upload.wikimedia.org/image.jpg"]
    assert result[0][3] == [
        {
            "url": "https://upload.wikimedia.org/image.jpg",
            "source_url": "https://commons.wikimedia.org/wiki/File:Image.jpg",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution_required": True,
            "attribution": "Creator / Wikimedia Commons / CC BY 4.0",
        }
    ]
    assert result[0][4] is not None
    assert result[0][5] is not None


@pytest.mark.asyncio
async def test_reuses_existing_cluster_images_without_api_call(monkeypatch: pytest.MonkeyPatch):
    async def fail_if_called(titles: list[str]):
        raise AssertionError("Wikimedia should not be queried for an unchanged cluster")

    monkeypatch.setattr(
        clustering_module, "lookup_wikimedia_images_for_clusters", fail_if_called
    )
    lookup_at = datetime.now(timezone.utc)
    payloads = [
        (
            "Existing cluster",
            [],
            ["https://upload.wikimedia.org/existing.jpg"],
            [
                {
                    "url": "https://upload.wikimedia.org/existing.jpg",
                    "source_url": "https://commons.wikimedia.org/wiki/File:Existing.jpg",
                    "license": "CC0",
                }
            ],
            lookup_at,
            lookup_at,
        )
    ]

    result = await clustering_module.enrich_cluster_payloads_with_wikimedia(payloads)

    assert result == payloads


@pytest.mark.asyncio
async def test_lookup_failure_does_not_abort_clustering(monkeypatch: pytest.MonkeyPatch):
    async def fail(titles: list[str]):
        raise RuntimeError("Wikimedia is unavailable")

    monkeypatch.setattr(clustering_module, "lookup_wikimedia_images_for_clusters", fail)
    payloads = [("New cluster", [], [], [], None, None)]

    result = await clustering_module.enrich_cluster_payloads_with_wikimedia(payloads)

    assert result == payloads


@pytest.mark.asyncio
async def test_clears_image_urls_without_matching_license_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    async def lookup_images(titles: list[str]):
        assert titles == ["Incomplete cluster"]
        return [FakeLookupResult([])]

    monkeypatch.setattr(
        clustering_module, "lookup_wikimedia_images_for_clusters", lookup_images
    )
    payloads = [
        (
            "Incomplete cluster",
            [],
            ["https://upload.wikimedia.org/unlicensed.jpg"],
            [],
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
        )
    ]

    result = await clustering_module.enrich_cluster_payloads_with_wikimedia(payloads)

    assert result[0][:4] == ("Incomplete cluster", [], [], [])
    assert result[0][4] is not None
    assert result[0][5] is not None


@pytest.mark.asyncio
async def test_limits_wikimedia_requests_per_clustering_run(
    monkeypatch: pytest.MonkeyPatch,
):
    requested_titles: list[str] = []

    async def lookup_images(titles: list[str]):
        requested_titles.extend(titles)
        return [
            FakeLookupResult(
                [FakeWikimediaImage(f"https://upload.wikimedia.org/{title}.jpg")]
            )
            for title in titles
        ]

    monkeypatch.setattr(clustering_module, "MAX_WIKIMEDIA_LOOKUPS_PER_RUN", 2)
    monkeypatch.setattr(
        clustering_module, "lookup_wikimedia_images_for_clusters", lookup_images
    )
    payloads = [(f"Cluster {index}", [], [], [], None, None) for index in range(5)]

    result = await clustering_module.enrich_cluster_payloads_with_wikimedia(payloads)

    assert len(requested_titles) == 2
    assert sum(bool(payload[2]) for payload in result) == 2
    assert sum(payload[4] is not None for payload in result) == 2
    assert sum(payload[5] is not None for payload in result) == 2


@pytest.mark.asyncio
async def test_persists_a_completed_no_match_and_does_not_query_it_again(
    monkeypatch: pytest.MonkeyPatch,
):
    async def no_match(titles: list[str]):
        return [FakeLookupResult([]) for _ in titles]

    monkeypatch.setattr(
        clustering_module, "lookup_wikimedia_images_for_clusters", no_match
    )
    payloads = [("No matching page", [], [], [], None, None)]
    first_result = await clustering_module.enrich_cluster_payloads_with_wikimedia(payloads)

    async def fail_if_called(titles: list[str]):
        raise AssertionError("A completed no-match should be persisted")

    monkeypatch.setattr(
        clustering_module, "lookup_wikimedia_images_for_clusters", fail_if_called
    )
    second_result = await clustering_module.enrich_cluster_payloads_with_wikimedia(
        first_result
    )

    assert first_result[0][4] is not None
    assert first_result[0][5] is not None
    assert second_result == first_result


@pytest.mark.asyncio
async def test_transient_per_cluster_failure_remains_eligible_for_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    async def transient_failure(titles: list[str]):
        return [FakeLookupResult([], completed=False) for _ in titles]

    monkeypatch.setattr(
        clustering_module,
        "lookup_wikimedia_images_for_clusters",
        transient_failure,
    )
    payloads = [("Retry later", [], [], [], None, None)]

    result = await clustering_module.enrich_cluster_payloads_with_wikimedia(payloads)

    assert result[0][:5] == payloads[0][:5]
    assert result[0][5] is not None


@pytest.mark.asyncio
async def test_bounded_batches_eventually_attempt_every_cluster(
    monkeypatch: pytest.MonkeyPatch,
):
    requested_titles: list[str] = []

    async def no_match(titles: list[str]):
        requested_titles.extend(titles)
        return [FakeLookupResult([]) for _ in titles]

    monkeypatch.setattr(clustering_module, "MAX_WIKIMEDIA_LOOKUPS_PER_RUN", 2)
    monkeypatch.setattr(
        clustering_module, "lookup_wikimedia_images_for_clusters", no_match
    )
    payloads = [(f"Cluster {index}", [], [], [], None, None) for index in range(5)]

    for _ in range(3):
        payloads = await clustering_module.enrich_cluster_payloads_with_wikimedia(
            payloads
        )

    assert requested_titles == [f"Cluster {index}" for index in range(5)]
    assert all(payload[4] is not None for payload in payloads)
    assert all(payload[5] is not None for payload in payloads)


@pytest.mark.asyncio
async def test_persistent_failures_do_not_starve_never_attempted_clusters(
    monkeypatch: pytest.MonkeyPatch,
):
    requested_titles: list[str] = []

    async def fail_each_title(titles: list[str]):
        requested_titles.extend(titles)
        return [FakeLookupResult([], completed=False) for _ in titles]

    monkeypatch.setattr(clustering_module, "MAX_WIKIMEDIA_LOOKUPS_PER_RUN", 2)
    monkeypatch.setattr(
        clustering_module,
        "lookup_wikimedia_images_for_clusters",
        fail_each_title,
    )
    payloads = [(f"Cluster {index}", [], [], [], None, None) for index in range(5)]

    for _ in range(3):
        payloads = await clustering_module.enrich_cluster_payloads_with_wikimedia(
            payloads
        )

    assert requested_titles == [f"Cluster {index}" for index in range(5)]
    assert all(payload[4] is None for payload in payloads)
    assert all(payload[5] is not None for payload in payloads)
