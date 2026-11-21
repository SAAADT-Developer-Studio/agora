"""The packaged ranking file is the job's source of truth."""

from json import dumps, loads
import logging
from pathlib import Path

import pytest
import yaml

from app.ranking.config_file import (
    CONTAINER_RANKING_CONFIG_PATH,
    RankingConfigFileError,
    load_ranking_config_file,
    load_ranking_job_config,
    packaged_ranking_config_path,
    packaged_ranking_schema_path,
    ranking_config_json_schema,
)
from app.ranking.contracts import RankingConfig
from app.ranking.persistence import DEFAULT_CONFIG_VERSION, resolve_ranking_config


def _parameter_bytes(config: RankingConfig) -> bytes:
    payload = config.model_dump(mode="json")["parameters"]
    return dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


# Exact recommended-v2 object. Whole numbers are ints here; the models store floats.
RECOMMENDED_V2_PARAMETERS = {
    "article_contribution": {
        "authority_weight": 0.25, "originality_weight": 0.2, "novelty_weight": 0.3,
        "quality_weight": 0.15, "source_weight": 0.1, "freshness_half_life_hours": 24,
        "publisher_repeat_decay": 0.5, "normalization_scale": 3, "unknown_authority": 0.5,
        "unknown_originality": 0.5, "unknown_novelty": 0.5, "unknown_source_credit": 0.25,
        "unknown_syndication_multiplier": 0.85, "syndication_multiplier": 0.35,
        "syndicated_originality_cap": 0.15, "family_distribution_credit": 0.15,
        "family_distribution_decay": 0.5, "breaking_credit": 0.75,
        "semantic_novelty_weight": 0.7, "novelty_similarity_floor": 0.7,
        "redundancy_similarity": 0.98, "minimum_text_tokens": 12,
        "full_content_tokens": 200, "full_summary_tokens": 40,
    },
    "syndication": {
        "minimum_content_tokens": 50, "minimum_unique_shingles": 20, "similarity_threshold": 0.8,
    },
    "coverage": {
        "normalization_scale": 5, "unknown_publisher_weight": 0.5,
        "syndicated_publisher_weight": 0.15, "family_distribution_credit": 0.15,
        "family_distribution_decay": 0.5,
    },
    "publisher_authority": {"unknown_authority": 0.5},
    "freshness": {
        "default_half_life_hours": 24,
        "category_half_lives_hours": {
            "politika": 24, "gospodarstvo": 36, "kriminal": 12, "sport": 6, "kultura": 24,
            "zdravje": 48, "okolje": 48, "lokalno": 24, "tehnologija-znanost": 72,
        },
        "minimum_novelty": 0.5, "minimum_new_text_fraction": 0.2,
    },
    "momentum": {
        "window_hours": 6, "new_publisher_weight": 0.5, "publisher_repeat_credit": 0.15,
        "publisher_repeat_decay": 0.5, "minimum_novelty": 0.5, "minimum_new_text_fraction": 0.2,
        "velocity_scale_per_hour": 0.5, "acceleration_weight": 0.4,
    },
    "newsworthiness": {
        "top_reports": 3, "strongest_weight": 0.5, "unknown_importance": 0.5,
        "cluster_score_weight": 1,
    },
    "cluster_confidence": {
        "outlier_similarity": 0.4, "weak_similarity": 0.75, "strong_similarity": 0.9,
        "outlier_membership": 0.2, "weak_membership": 0.5, "semantic_weight": 0.7,
        "unknown_similarity_score": 0.5, "unknown_membership_confidence": 0.5,
        "weak_relation_penalty": 0.5, "temporal_half_life_hours": 72, "temporal_penalty": 0.25,
        "gate_power": 1,
    },
    "ranking": {
        "article_contribution_weight": 0.5, "coverage_weight": 1, "momentum_weight": 1.5,
        "semantic_importance_weight": 2,
        "article_strength": {
            "authority_weight": 0.5, "data_quality_weight": 0.3, "source_weight": 0.2,
        },
    },
}


def _leaf_diffs(left, right, prefix=""):
    if isinstance(left, dict) and isinstance(right, dict):
        diffs = []
        for key in sorted(left.keys() | right.keys()):
            path = f"{prefix}.{key}" if prefix else key
            if key not in left or key not in right:
                diffs.append(path)
            else:
                diffs.extend(_leaf_diffs(left[key], right[key], path))
        return diffs
    if left != right:
        return [prefix]
    return []


def test_committed_yaml_is_recommended_v2_and_round_trips():
    path = packaged_ranking_config_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    expected = resolve_ranking_config(RankingConfig(
        version="recommended-v2", parameters=RECOMMENDED_V2_PARAMETERS,
    ))
    assert raw["version"] == "recommended-v2"
    loaded = load_ranking_config_file(path)
    assert loaded.version == "recommended-v2"
    assert loaded.model_dump(mode="json") == expected.model_dump(mode="json")
    # Every parameter is written in the file. Loading does not fill a different value.
    assert raw["parameters"] == loaded.parameters
    defaults = resolve_ranking_config(RankingConfig(version=DEFAULT_CONFIG_VERSION))
    assert _leaf_diffs(defaults.parameters, loaded.parameters) == [
        "freshness.category_half_lives_hours.kultura",
        "ranking.article_contribution_weight",
        "ranking.momentum_weight",
        "ranking.semantic_importance_weight",
    ]
    assert loaded.parameters["freshness"]["category_half_lives_hours"]["kultura"] == 24.0
    assert loaded.parameters["ranking"]["article_contribution_weight"] == 0.5
    assert loaded.parameters["ranking"]["momentum_weight"] == 1.5
    assert loaded.parameters["ranking"]["semantic_importance_weight"] == 2.0
    # JSON and YAML dumps of the resolved object load back to the same parameters.
    blob = loaded.model_dump(mode="json")
    again = resolve_ranking_config(RankingConfig.model_validate(blob))
    assert again.model_dump(mode="json") == blob
    assert _parameter_bytes(again) == _parameter_bytes(loaded)


def test_committed_schema_matches_the_config_models():
    # If a config model changes, rewrite ranking.schema.json from ranking_config_json_schema().
    committed = packaged_ranking_schema_path().read_text(encoding="utf-8")
    assert committed.endswith("\n")
    assert loads(committed) == ranking_config_json_schema()
    sections = ranking_config_json_schema()["properties"]["parameters"]["properties"]
    raw = yaml.safe_load(packaged_ranking_config_path().read_text(encoding="utf-8"))
    assert set(raw["parameters"]) == set(sections)


def test_image_and_systemd_unit_read_the_packaged_file():
    repo = Path(__file__).resolve().parents[4]
    dockerfile = (repo / "scraper" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY scraper scraper" in dockerfile
    assert "test -s scraper/config/ranking.yaml" in dockerfile
    deploy = (repo / "ansible" / "deploy.yml").read_text(encoding="utf-8")
    assert f"--config {CONTAINER_RANKING_CONFIG_PATH}" in deploy
    packaged = packaged_ranking_config_path()
    assert packaged == repo / "scraper" / "config" / "ranking.yaml"
    assert Path("/app") / packaged.relative_to(repo) == CONTAINER_RANKING_CONFIG_PATH
    ignored = {
        line.strip() for line in (repo / ".dockerignore").read_text(encoding="utf-8").splitlines()
    }
    assert not ignored.intersection({"*.yaml", "*.yml", "config", "scraper/config", "**/config/**"})


def test_yml_suffix_loads_the_same_document(tmp_path):
    path = tmp_path / "ranking.yml"
    path.write_text(packaged_ranking_config_path().read_text(encoding="utf-8"), encoding="utf-8")
    loaded = load_ranking_config_file(path)
    packaged = load_ranking_config_file(packaged_ranking_config_path())
    assert loaded.model_dump_json() == packaged.model_dump_json()


def test_resolved_config_round_trips_through_yaml_and_json(tmp_path):
    loaded = load_ranking_config_file(packaged_ranking_config_path())
    blob = loaded.model_dump(mode="json")
    json_path = tmp_path / "ranking.json"
    json_path.write_text(dumps(blob), encoding="utf-8")
    yaml_path = tmp_path / "ranking.yaml"
    yaml_path.write_text(
        yaml.safe_dump(blob, sort_keys=False, allow_unicode=True), encoding="utf-8",
    )
    from_json = load_ranking_config_file(json_path)
    from_yaml = load_ranking_config_file(yaml_path)
    assert from_json.model_dump(mode="json") == blob
    assert from_yaml.model_dump(mode="json") == blob
    assert _parameter_bytes(from_json) == _parameter_bytes(from_yaml) == _parameter_bytes(loaded)


def test_backoffice_json_export_loads(tmp_path):
    defaults = resolve_ranking_config(RankingConfig(version=DEFAULT_CONFIG_VERSION))
    path = tmp_path / "preset.json"
    path.write_text(defaults.model_dump_json(), encoding="utf-8")
    loaded = load_ranking_config_file(path)
    assert loaded.model_dump_json() == defaults.model_dump_json()
    assert _parameter_bytes(loaded) == _parameter_bytes(defaults)


def test_partial_backoffice_json_keeps_the_override_and_fills_the_rest(tmp_path):
    path = tmp_path / "preset.json"
    path.write_text(dumps({
        "version": "backoffice-preset",
        "parameters": {"ranking": {"coverage_weight": 2}},
    }), encoding="utf-8")
    loaded = load_ranking_config_file(path)
    expected = resolve_ranking_config(RankingConfig(
        version="backoffice-preset",
        parameters={"ranking": {"coverage_weight": 2}},
    ))
    assert loaded.model_dump_json() == expected.model_dump_json()
    assert loaded.parameters["ranking"]["coverage_weight"] == 2
    assert loaded.parameters["ranking"]["momentum_weight"] == 1.0


@pytest.mark.parametrize(("name", "text", "match"), [
    ("bad.yaml", "version: [\n", "invalid YAML"),
    ("bad.json", "{", "invalid JSON"),
    ("notes.txt", "version: x\n", r"\.yaml, \.yml, or \.json"),
    ("empty.yaml", "", "empty"),
    ("list.yaml", "- 1\n", "expected an object"),
    ("two.yaml", "version: a\n---\nversion: b\n", "exactly one document"),
    (
        "nan.yaml",
        "version: v\nparameters:\n  ranking:\n    coverage_weight: .nan\n",
        "JSON-compatible",
    ),
    ("unknown.yaml", "version: v\nparameters:\n  typo: {}\n", "Unknown ranking"),
    ("unknown.json", '{"version":"v","parameters":{"typo":{}}}', "Unknown ranking"),
    (
        "bad-value.yaml",
        "version: v\nparameters:\n  coverage:\n    normalization_scale: 0\n",
        "invalid settings",
    ),
    ("extra.yaml", "version: v\nparameters:\n  ranking:\n    typo: 1\n", "invalid settings"),
])
def test_invalid_config_files_are_rejected(tmp_path, name, text, match):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RankingConfigFileError, match=match):
        load_ranking_config_file(path)
    with pytest.raises(RankingConfigFileError, match="not used for an unreadable or invalid"):
        load_ranking_config_file(path)


def test_missing_config_file_is_rejected_by_the_loader(tmp_path):
    missing = tmp_path / "ranking.yaml"
    with pytest.raises(RankingConfigFileError, match="not found") as exc:
        load_ranking_config_file(missing)
    assert "not used for an unreadable or invalid" in str(exc.value)


def test_job_falls_back_when_the_file_is_missing(monkeypatch, caplog, tmp_path):
    from scripts import rank_clusters

    seen = {}
    monkeypatch.setattr(
        rank_clusters, "run_ranking",
        lambda args, config: seen.update(args=args, config=config),
    )
    missing = tmp_path / "missing.yaml"
    with caplog.at_level(logging.ERROR):
        rank_clusters.main(["--config", str(missing)])
    defaults = resolve_ranking_config(RankingConfig(version=DEFAULT_CONFIG_VERSION))
    assert seen["config"].model_dump_json() == defaults.model_dump_json()
    assert seen["config"].version == "initial-ranking-v1"
    assert seen["args"].config == missing
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors
    assert "missing" in caplog.text
    assert "Falling back to hardcoded Python defaults" in caplog.text
    assert DEFAULT_CONFIG_VERSION in caplog.text
    fallback = load_ranking_job_config(missing)
    assert fallback.model_dump_json() == defaults.model_dump_json()


def test_main_fails_closed_when_the_file_is_invalid(monkeypatch, caplog, tmp_path):
    from scripts import rank_clusters

    def fail_if_called(*_args):
        raise AssertionError("ranking ran with an invalid config file")

    monkeypatch.setattr(rank_clusters, "run_ranking", fail_if_called)
    path = tmp_path / "broken.yaml"
    path.write_text("version: [\n", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit) as exc:
            rank_clusters.main(["--config", str(path)])
    assert exc.value.code == 1
    assert "invalid YAML" in caplog.text


def test_main_defaults_to_the_packaged_yaml(monkeypatch, caplog):
    from scripts import rank_clusters

    seen = {}
    monkeypatch.setattr(
        rank_clusters, "run_ranking",
        lambda args, config: seen.update(args=args, config=config),
    )
    with caplog.at_level(logging.INFO):
        rank_clusters.main([])
    packaged = load_ranking_config_file(packaged_ranking_config_path())
    assert seen["args"].config == packaged_ranking_config_path()
    assert seen["config"].model_dump_json() == packaged.model_dump_json()
    assert seen["config"].version == "recommended-v2"
    assert seen["config"].parameters["ranking"]["semantic_importance_weight"] == 2.0
    assert seen["config"].parameters["freshness"]["category_half_lives_hours"]["kultura"] == 24.0
    assert "Loaded ranking config" in caplog.text
    assert "recommended-v2" in caplog.text
    assert "Falling back" not in caplog.text


def test_main_loads_a_backoffice_json_preset(monkeypatch, tmp_path):
    from scripts import rank_clusters

    seen = {}
    monkeypatch.setattr(
        rank_clusters, "run_ranking",
        lambda args, config: seen.update(args=args, config=config),
    )
    path = tmp_path / "preset.json"
    path.write_text(dumps({
        "version": "backoffice-preset",
        "parameters": {"freshness": {"default_half_life_hours": 10}},
    }), encoding="utf-8")
    rank_clusters.main(["--config", str(path), "--dry-run"])
    assert seen["args"].config == path
    assert seen["args"].dry_run is True
    assert seen["config"].version == "backoffice-preset"
    assert seen["config"].parameters["freshness"]["default_half_life_hours"] == 10
    assert seen["config"].parameters["freshness"]["minimum_novelty"] == 0.5


def test_help_does_not_read_the_config_file(capsys):
    from scripts.rank_clusters import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "ranking.yaml" in capsys.readouterr().out
