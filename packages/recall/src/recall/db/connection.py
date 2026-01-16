from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import os

import duckdb

from recall.core.config import AppConfig
from recall.db.schema import ensure_schema


class RecallLockError(RuntimeError):
    pass


@contextmanager
def advisory_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as handle:
        try:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as err:
            raise RecallLockError("another recall index is running") from err
        try:
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                pass


def connect(config: AppConfig, *, recreate: bool = False) -> duckdb.DuckDBPyConnection:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if recreate:
        _backup_database(config.db_path)
    conn = duckdb.connect(str(config.db_path))
    ensure_schema(conn)
    return conn


def _backup_database(db_path: Path) -> None:
    if not db_path.exists():
        return
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    backup_path = db_path.with_suffix(f".bak-{timestamp}")
    os.replace(db_path, backup_path)
    wal_path = db_path.with_suffix(db_path.suffix + ".wal")
    if wal_path.exists():
        os.replace(wal_path, wal_path.with_suffix(wal_path.suffix + f".{timestamp}.bak"))
