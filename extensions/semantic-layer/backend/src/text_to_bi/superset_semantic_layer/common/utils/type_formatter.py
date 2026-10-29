import json
from datetime import date, datetime, timezone
from typing import Any


def iso_datetime(value: datetime | date | None) -> str | None:
    """A stored date or timestamp in ISO 8601, or None when it is not set."""
    return value.isoformat() if value else None


def iso_date(value: Any) -> str | None:
    """A ChartData date as YYYY-MM-DD; the driver gives a date, a timestamp, a string or epoch milliseconds."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value[:10]
    return None


def iso_moment(value: Any) -> str | None:
    """A ChartData moment in ISO 8601; the driver gives a datetime, a date, an ISO string or epoch milliseconds."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None).isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def json_list(value: Any) -> list[str]:
    """A list stored as JSON text; anything unreadable reads as empty."""
    if not value:
        return []
    try:
        items = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [item for item in items if isinstance(item, str)] if isinstance(items, list) else []


def compact_json(value: Any) -> str:
    """JSON without spaces, for layouts stored in a text column."""
    return json.dumps(value, separators=(",", ":"))


def canonical_json(payload: Any) -> str:
    """One stable JSON text for a payload, with sorted keys, so equal payloads hash alike."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sse_event(name: str, data: dict[str, Any]) -> str:
    """One server-sent event carrying `data` as JSON."""
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
