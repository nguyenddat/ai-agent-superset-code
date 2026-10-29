import json
from datetime import date, datetime
from typing import Any


def iso_datetime(value: datetime | date | None) -> str | None:
    """A stored date or timestamp in ISO 8601, or None when it is not set."""
    return value.isoformat() if value else None


def sse_event(name: str, data: dict[str, Any]) -> str:
    """One server-sent event carrying `data` as JSON."""
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
