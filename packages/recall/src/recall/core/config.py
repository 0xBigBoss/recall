from __future__ import annotations

import os
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FTS_FIELDS = ("content", "thinking", "bash")
VALID_FTS_FIELDS = {"content", "thinking", "bash"}


@dataclass(frozen=True)
class FtsConfig:
    fields: tuple[str, ...] = DEFAULT_FTS_FIELDS

    @classmethod
    def from_values(cls, values: Iterable[str] | None) -> FtsConfig:
        if values is None:
            return cls()
        normalized = tuple(field.strip() for field in values if field.strip())
        if not normalized:
            return cls(fields=())
        invalid = [field for field in normalized if field not in VALID_FTS_FIELDS]
        if invalid:
            raise ValueError(f"invalid FTS fields: {', '.join(invalid)}")
        return cls(fields=normalized)


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    db_path: Path
    lock_path: Path
    config_path: Path
    fts: FtsConfig

    @classmethod
    def load(cls) -> AppConfig:
        home = Path.home()
        default_data_dir = Path(os.environ.get("RECALL_DATA_DIR", home / ".local/share/recall"))
        default_config_path = Path(
            os.environ.get("RECALL_CONFIG_PATH", home / ".config/recall/config.toml")
        )
        db_path = Path(os.environ.get("RECALL_DB_PATH", default_data_dir / "recall.duckdb"))
        lock_path = Path(os.environ.get("RECALL_LOCK_PATH", default_data_dir / "recall.lock"))

        file_fields = None
        if default_config_path.exists():
            raw = default_config_path.read_text(encoding="utf-8")
            data = tomllib.loads(raw) if raw.strip() else {}
            fts_section = data.get("fts", {}) if isinstance(data, dict) else {}
            if isinstance(fts_section, dict):
                file_fields = fts_section.get("fields")

        env_fields = os.environ.get("RECALL_FTS_FIELDS")
        fts_values = None
        if env_fields is not None:
            fts_values = [field.strip() for field in env_fields.split(",")]
        elif isinstance(file_fields, list):
            fts_values = [str(field) for field in file_fields]

        fts = FtsConfig.from_values(fts_values)
        return cls(
            data_dir=default_data_dir,
            db_path=db_path,
            lock_path=lock_path,
            config_path=default_config_path,
            fts=fts,
        )
