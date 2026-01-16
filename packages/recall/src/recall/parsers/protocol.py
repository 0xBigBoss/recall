from __future__ import annotations

from pathlib import Path
from typing import Protocol

from recall.core.models import Session
from recall.core.types import Source


class SessionParser(Protocol):
    source: Source

    def discover(self) -> list[Path]:
        ...

    def parse(self, path: Path) -> Session:
        ...
