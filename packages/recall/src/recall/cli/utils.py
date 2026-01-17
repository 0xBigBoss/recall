from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

import typer
from pydantic import BaseModel


def json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return value.model_dump()
    if is_dataclass(value):
        return asdict(value)
    return str(value)


def print_json(data: Any) -> None:
    typer.echo(json.dumps(data, default=json_default, indent=2))


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    return value.strftime("%Y-%m-%d %H:%M")
