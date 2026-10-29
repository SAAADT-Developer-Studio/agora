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
    packaged_ranking_config_path,
    packaged_ranking_schema_path,
    ranking_config_json_schema,
)
from app.ranking.contracts import RankingConfig
from app.ranking.persistence import DEFAULT_CONFIG_VERSION, resolve_ranking_config


def _parameter_bytes(config: RankingConfig) -> bytes:
    payload = config.model_dump(mode="json")["parameters"]
    return dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def test_committed_yaml_matches_code_defaults_byte_for_byte():
    path = packaged_ranking_config_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = resolve_ranking_config(RankingConfig(version=DEFAULT_CONFIG_VERSION))
    assert raw["version"] == DEFAULT_CONFIG_VERSION == "initial-ranking-v1"
    # Every parameter is written in the file. Equality here is before fill-in.
    assert raw["parameters"] == defaults.parameters
    loaded = load_ranking_config_file(path)
    assert _parameter_bytes(loaded) == _parameter_bytes(defaults)
    assert loaded.model_dump_json() == defaults.model_dump_json()


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
    defaults = resolve_ranking_config(RankingConfig(version=DEFAULT_CONFIG_VERSION))
    assert loaded.model_dump_json() == defaults.model_dump_json()


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
    with pytest.raises(RankingConfigFileError, match="will not fall back"):
        load_ranking_config_file(path)


def test_missing_config_file_is_rejected(tmp_path):
    missing = tmp_path / "ranking.yaml"
    with pytest.raises(RankingConfigFileError, match="not found") as exc:
        load_ranking_config_file(missing)
    assert "will not fall back" in str(exc.value)


def test_main_fails_closed_when_the_file_is_missing(monkeypatch, caplog, tmp_path):
    from scripts import rank_clusters

    def fail_if_called(*_args):
        raise AssertionError("ranking ran without a config file")

    monkeypatch.setattr(rank_clusters, "run_ranking", fail_if_called)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit) as exc:
            rank_clusters.main(["--config", str(tmp_path / "missing.yaml")])
    assert exc.value.code == 1
    assert "not found" in caplog.text
    assert "will not fall back" in caplog.text


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
    defaults = resolve_ranking_config(RankingConfig(version=DEFAULT_CONFIG_VERSION))
    assert seen["args"].config == packaged_ranking_config_path()
    assert seen["config"].model_dump_json() == defaults.model_dump_json()
    assert "Loaded ranking config" in caplog.text
    assert DEFAULT_CONFIG_VERSION in caplog.text


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
