"""Load the ranking job's {version, parameters} file.

The packaged YAML is the source of truth for the nightly observation run.
A missing or invalid file raises ``RankingConfigFileError``. Callers must
not substitute the Python field defaults in that case. ``resolve_ranking_config``
still fills omitted keys inside a file that parses, and still rejects unknown
sections and invalid values.
"""

from json import JSONDecodeError, dumps, loads
from pathlib import Path

from pydantic import ValidationError
import yaml

from app.ranking.contracts import RankingConfig
from app.ranking.persistence import CONFIG_SECTIONS, resolve_ranking_config


# Image root is /app and the Dockerfile copies the scraper tree there.
# ansible/deploy.yml passes this path to scripts.rank_clusters.
CONTAINER_RANKING_CONFIG_PATH = Path("/app/scraper/config/ranking.yaml")


class RankingConfigFileError(ValueError):
    """The ranking file cannot be used. Callers must not substitute defaults."""


def packaged_ranking_config_path() -> Path:
    """``scraper/config/ranking.yaml`` beside this package, including in the image."""
    return Path(__file__).resolve().parents[2] / "config" / "ranking.yaml"


def packaged_ranking_schema_path() -> Path:
    return packaged_ranking_config_path().with_name("ranking.schema.json")


def ranking_config_json_schema() -> dict:
    """Schema for the object the backoffice writes. The models enforce it at runtime."""
    sections = {name: model.model_json_schema() for name, model in CONFIG_SECTIONS.items()}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "ranking.schema.json",
        "title": "RankingConfig",
        "description": (
            "Story ranking settings. The file in git is scraper/config/ranking.yaml. "
            "See scraper/config/README.md."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "parameters"],
        "properties": {
            "version": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Label stored on ranking_run.config. "
                    "The current production value is initial-ranking-v1."
                ),
            },
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "description": (
                    "Fixed section names. Unknown sections are rejected. "
                    "Omitted sections and keys are filled from the Python models "
                    "when a valid file is loaded. Write every parameter explicitly."
                ),
                "properties": sections,
            },
        },
    }


def load_ranking_config_file(path: Path) -> RankingConfig:
    """Read a YAML or JSON ranking file and validate it.

    Raises ``RankingConfigFileError`` when the file is missing, unreadable,
    or invalid.
    """
    document = _read_document(Path(path))
    try:
        parsed = RankingConfig.model_validate(document)
    except ValidationError as exc:
        raise _reject(path, f"invalid settings: {exc}") from exc
    try:
        return resolve_ranking_config(parsed)
    except ValidationError as exc:
        raise _reject(path, f"invalid settings: {exc}") from exc
    except ValueError as exc:
        raise _reject(path, str(exc)) from exc


def _reject(path: Path, reason: str) -> RankingConfigFileError:
    return RankingConfigFileError(
        f"Ranking config file {path} cannot be used ({reason}). "
        "The ranking job will not fall back to code defaults."
    )


def _read_document(path: Path) -> dict:
    if not path.is_file():
        raise _reject(
            path,
            "not found. Expected scraper/config/ranking.yaml "
            f"({CONTAINER_RANKING_CONFIG_PATH} in the scraper image)",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _reject(path, f"could not be read: {exc}") from exc

    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            documents = list(yaml.safe_load_all(text))
        except yaml.YAMLError as exc:
            raise _reject(path, f"invalid YAML: {exc}") from exc
        if len(documents) != 1:
            raise _reject(path, "YAML must contain exactly one document")
        payload = documents[0]
    elif suffix == ".json":
        try:
            payload = loads(text)
        except JSONDecodeError as exc:
            raise _reject(path, f"invalid JSON: {exc}") from exc
    else:
        raise _reject(path, "path must end in .yaml, .yml, or .json")

    if not isinstance(payload, dict):
        kind = "empty" if payload is None else type(payload).__name__
        raise _reject(path, f"expected an object with version and parameters, got {kind}")
    try:
        document = loads(dumps(payload, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise _reject(path, f"values must be JSON-compatible: {exc}") from exc
    if not isinstance(document, dict):
        raise _reject(path, "expected an object with version and parameters")
    return document
