"""What a dataset's rows stand for in time: its time column, the column that tells its kinds of rows apart, and the
grain of each kind.

`fact_tong_hop_thoi_tiet` keeps hourly forecasts (`loai_quan_sat = 'DU_BAO_GIO'`), daily forecasts (`DU_BAO_NGAY`,
always at midnight) and current observations taken at odd times (`HIEN_TAI`) in one table, so a grain is declared per
kind of row rather than per dataset. A dataset with one kind of row has one grain, stored with no row kind value.

The grain profile reads, through Superset ChartData, how the time column's values fall for each kind of row, so the
administrator is offered a grain rather than asked to know it; nothing is saved until they save the dictionary.
"""

import re
from datetime import date, datetime, timezone
from typing import Any

# From finest to coarsest; `instant` rows are taken at irregular moments.
GRAINS = ("instant", "hour", "day", "week", "month", "quarter", "year")
TEMPORAL_KINDS = ("date", "timestamp")
MAX_ROW_KINDS = 20
MAX_LABEL_LENGTH = 255
MAX_ROW_KIND_VALUE_LENGTH = 255
SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TIMESTAMP_TYPE = re.compile(r"TIMESTAMP|DATETIME", re.IGNORECASE)
_DATE_TYPE = re.compile(r"^\s*DATE\s*$", re.IGNORECASE)


def default_temporal_kind(data_type: Any, is_dttm: bool) -> str | None:
    """`timestamp` or `date` read from the column's type; a column Superset marks temporal without a known type is a
    timestamp, the kind that keeps every time of day."""
    text = str(data_type or "")
    if _TIMESTAMP_TYPE.search(text):
        return "timestamp"
    if _DATE_TYPE.match(text):
        return "date"
    return "timestamp" if is_dttm else None


def checked_temporal_kind(value: Any, index: int) -> str | None:
    if value is not None and value not in TEMPORAL_KINDS:
        raise ValueError(f"columns[{index}].temporal_kind must be 'date', 'timestamp' or null.")
    return value


def checked_time_semantics(
    time_column: Any, row_kind_column: Any, grains: Any, temporal_kinds: dict[str, str | None],
) -> list[dict[str, Any]]:
    """The grains to store, checked against the dataset's columns as they will be once saved.

    `temporal_kinds` maps every column of the dataset to its temporal kind after the save. Raises ValueError with a
    message for the administrator.
    """
    if time_column is not None:
        if not isinstance(time_column, str) or time_column not in temporal_kinds:
            raise ValueError("dataset.time_column must be a column of this dataset or null.")
        if temporal_kinds[time_column] is None:
            raise ValueError("dataset.time_column must be a date or timestamp column.")
    if row_kind_column is not None:
        if not isinstance(row_kind_column, str) or row_kind_column not in temporal_kinds:
            raise ValueError("dataset.row_kind_column must be a column of this dataset or null.")
        if row_kind_column == time_column:
            raise ValueError("dataset.row_kind_column must differ from dataset.time_column.")
        if time_column is None:
            raise ValueError("dataset.row_kind_column needs a dataset.time_column.")
    if not isinstance(grains, list):
        raise ValueError("dataset.grains must be an array.")  # noqa: TRY004
    if grains and time_column is None:
        raise ValueError("dataset.grains need a dataset.time_column.")
    if len(grains) > MAX_ROW_KINDS:
        raise ValueError(f"dataset.grains may have at most {MAX_ROW_KINDS} kinds of rows.")
    if row_kind_column is None and len(grains) > 1:
        raise ValueError("Several grains need a dataset.row_kind_column that tells the rows apart.")

    checked = []
    seen_values = set()
    for index, item in enumerate(grains):
        if not isinstance(item, dict) or set(item) - {"row_kind_value", "label", "grain"}:
            raise ValueError(f"dataset.grains[{index}] must hold only row_kind_value, label and grain.")
        value = item.get("row_kind_value")
        if row_kind_column is None:
            if value is not None:
                raise ValueError(f"dataset.grains[{index}].row_kind_value needs a dataset.row_kind_column.")
        elif not isinstance(value, str) or not value.strip() or len(value) > MAX_ROW_KIND_VALUE_LENGTH:
            raise ValueError(f"dataset.grains[{index}].row_kind_value must be a value of {row_kind_column}.")
        if value in seen_values:
            raise ValueError(f"dataset.grains has the kind of row {value} twice.")
        seen_values.add(value)
        label = item.get("label")
        if label is not None and (not isinstance(label, str) or len(label) > MAX_LABEL_LENGTH):
            raise ValueError(f"dataset.grains[{index}].label must be a string of at most {MAX_LABEL_LENGTH} characters.")
        if item.get("grain") not in GRAINS:
            raise ValueError(f"dataset.grains[{index}].grain must be one of {', '.join(GRAINS)}.")
        checked.append({
            "row_kind_value": value,
            "label": (label or "").strip() or value,
            "grain": item["grain"],
        })
    return checked


def build_grain_profile_payload(
    dataset: Any, time_column: str, row_kind_column: str | None, temporal_kind: str,
) -> dict[str, Any]:
    """One aggregate row per kind of row: how many rows, the first and last moment, and how many fall off the hour, off
    midnight and off the first day of a month.

    Only EXTRACT, CAST to DATE and COUNT DISTINCT are used, so the query runs on the usual SQL engines. A date has no
    time of day, and PostgreSQL refuses EXTRACT(HOUR) on one, so a date column is not counted off the hour or midnight.
    Column names are checked as plain identifiers before they reach SQL.
    """
    for name in (time_column, row_kind_column):
        if name is not None and not SIMPLE_IDENTIFIER.match(name):
            raise ValueError("Grain detection needs plainly named columns.")
    hour, minute, second = (f"EXTRACT({part} FROM {time_column})" for part in ("HOUR", "MINUTE", "SECOND"))
    day = f"EXTRACT(DAY FROM {time_column})"

    def counted(condition: str, label: str) -> dict[str, Any]:
        return {
            "expressionType": "SQL",
            "sqlExpression": f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)",
            "label": label,
        }

    metrics = [
        {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "row_count"},
        {"expressionType": "SQL", "sqlExpression": f"MIN({time_column})", "label": "first_moment"},
        {"expressionType": "SQL", "sqlExpression": f"MAX({time_column})", "label": "last_moment"},
        {"expressionType": "SQL", "sqlExpression": f"COUNT(DISTINCT {time_column})", "label": "moments"},
        {"expressionType": "SQL", "sqlExpression": f"COUNT(DISTINCT CAST({time_column} AS DATE))", "label": "days"},
        counted(f"{day} <> 1", "off_first_day"),
    ]
    if temporal_kind == "timestamp":
        metrics += [
            counted(f"{minute} <> 0 OR {second} <> 0", "off_the_hour"),
            counted(f"{hour} <> 0 OR {minute} <> 0 OR {second} <> 0", "off_midnight"),
        ]
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [{
            "columns": [row_kind_column] if row_kind_column else [],
            "metrics": metrics,
            "row_limit": MAX_ROW_KINDS + 1,
        }],
        "result_type": "full",
        "result_format": "json",
    }


def _moment(value: Any) -> str | None:
    """ChartData gives a moment as a datetime, a date, an ISO string or epoch milliseconds, depending on the driver."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None).isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def _count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def suggested_grain(profile: dict[str, Any]) -> str | None:
    """The grain the values fit: irregular moments, whole hours, midnights, or first days of a month."""
    if profile["row_count"] == 0:
        return None
    if profile["off_the_hour"]:
        return "instant"
    if profile["off_midnight"]:
        return "hour"
    if not profile["off_first_day"] and profile["moments"] > 1:
        return "month"
    return "day"


def grain_profile_from_rows(
    rows: list[dict[str, Any]], row_kind_column: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """One profile per kind of row, sorted by its value, and whether the column holds more kinds than a grain list
    keeps; a kind of row with no time recorded is left out."""
    profiles = []
    for row in rows[:MAX_ROW_KINDS]:
        value = row.get(row_kind_column) if row_kind_column else None
        if row_kind_column and value in (None, ""):
            continue
        profile = {
            "row_kind_value": None if value is None else str(value),
            "row_count": _count(row.get("row_count")),
            "first_moment": _moment(row.get("first_moment")),
            "last_moment": _moment(row.get("last_moment")),
            "moments": _count(row.get("moments")),
            "days": _count(row.get("days")),
            "off_the_hour": _count(row.get("off_the_hour")),
            "off_midnight": _count(row.get("off_midnight")),
            "off_first_day": _count(row.get("off_first_day")),
        }
        profile["suggested_grain"] = suggested_grain(profile)
        profiles.append(profile)
    profiles.sort(key=lambda profile: profile["row_kind_value"] or "")
    return profiles, len(rows) > MAX_ROW_KINDS
