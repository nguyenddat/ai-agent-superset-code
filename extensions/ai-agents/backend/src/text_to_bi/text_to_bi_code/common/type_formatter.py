from datetime import datetime, timezone


def to_iso_text(value: datetime | None = None) -> str:
    """Convert a datetime to a UTC ISO 8601 string.

    Naive datetimes are treated as UTC. If no value is provided, the current
    UTC time is returned.
    """
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)

    return value.isoformat(timespec="microseconds")
