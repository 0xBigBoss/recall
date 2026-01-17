from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

_DURATION_RE = re.compile(r"^(\d+)([smhdw])$")


def parse_since(value: str, now: datetime | None = None) -> datetime:
    if not value:
        raise ValueError("since value is empty")
    match = _DURATION_RE.match(value)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        delta = _duration_delta(amount, unit)
        base = now or datetime.now(UTC)
        return base - delta

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as err:
        raise ValueError(f"invalid since value: {value}") from err

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _duration_delta(amount: int, unit: str) -> timedelta:
    match unit:
        case "s":
            return timedelta(seconds=amount)
        case "m":
            return timedelta(minutes=amount)
        case "h":
            return timedelta(hours=amount)
        case "d":
            return timedelta(days=amount)
        case "w":
            return timedelta(weeks=amount)
        case _:
            raise ValueError(f"unsupported duration unit: {unit}")
