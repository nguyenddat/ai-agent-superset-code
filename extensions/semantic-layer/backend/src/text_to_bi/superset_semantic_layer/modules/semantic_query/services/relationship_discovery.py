import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import case, column, func, select, table

SOURCES = ("database", "dictionary", "naming")
KEY_SUFFIX = re.compile(r"_(id|key)$", re.IGNORECASE)
MAX_ORPHAN_SAMPLES = 5
VERIFICATION_TIMEOUT_MS = 15_000
_TYPE_FAMILIES = (
    ("timestamp", re.compile(r"TIMESTAMP|DATETIME", re.IGNORECASE)),
    ("date", re.compile(r"^\s*DATE\s*$", re.IGNORECASE)),
    ("number", re.compile(r"INT|NUMERIC|DECIMAL|FLOAT|DOUBLE|REAL|SERIAL", re.IGNORECASE)),
    ("text", re.compile(r"CHAR|TEXT|STRING|UUID", re.IGNORECASE)),
    ("boolean", re.compile(r"BOOL", re.IGNORECASE)),
)


@dataclass(frozen=True)
class TableKeys:
    """A physical table as relationship discovery sees it: its columns with their types, and its key columns."""

    dataset_id: int
    schema: str | None
    table: str
    column_types: dict[str, str]
    # Columns that hold each value once on their own: a single-column primary key or a unique column.
    unique_columns: frozenset[str] = field(default_factory=frozenset)


def type_family(data_type: Any) -> str | None:
    text = str(data_type or "")
    return next((family for family, pattern in _TYPE_FAMILIES if pattern.search(text)), None)


def types_match(source_type: Any, target_type: Any) -> bool:
    """Whether two columns compare without a cast: the same family of types, such as BIGINT and INTEGER."""
    source_family, target_family = type_family(source_type), type_family(target_type)
    return source_family is not None and source_family == target_family


def _suggestion(source: TableKeys, source_column: str, target: TableKeys, target_column: str, origin: str):
    return {
        "from_dataset_id": source.dataset_id,
        "from_column": source_column,
        "to_dataset_id": target.dataset_id,
        "to_column": target_column,
        "sources": [origin],
    }


def naming_suggestions(tables: list[TableKeys]) -> list[dict[str, Any]]:
    """A column named `<x>_id` or `<x>_key` that matches, by name and type, a key column of another table."""
    suggestions = []
    for source in tables:
        for name, data_type in source.column_types.items():
            if not KEY_SUFFIX.search(name):
                continue
            for target in tables:
                if target.dataset_id == source.dataset_id or name not in target.unique_columns:
                    continue
                if types_match(data_type, target.column_types.get(name)):
                    suggestions.append(_suggestion(source, name, target, name, "naming"))
    return suggestions


def database_suggestions(
    tables: list[TableKeys], foreign_keys: dict[int, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """The database's single-column foreign keys between the given tables, as read by SQLAlchemy's inspector.

    `foreign_keys` maps a dataset ID to its inspector entries (`constrained_columns`, `referred_schema`,
    `referred_table`, `referred_columns`). A composite key or a table outside the given ones is left out.
    """
    by_name = {(item.schema, item.table): item for item in tables}
    by_id = {item.dataset_id: item for item in tables}
    suggestions = []
    for dataset_id, entries in foreign_keys.items():
        source = by_id.get(dataset_id)
        if source is None:
            continue
        for entry in entries:
            constrained, referred = entry.get("constrained_columns") or [], entry.get("referred_columns") or []
            if len(constrained) != 1 or len(referred) != 1:
                continue
            target = by_name.get((entry.get("referred_schema") or source.schema, entry.get("referred_table")))
            if target is None or constrained[0] not in source.column_types or referred[0] not in target.column_types:
                continue
            suggestions.append(_suggestion(source, constrained[0], target, referred[0], "database"))
    return suggestions


def merged_suggestions(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One suggestion per pair of columns, listing every source that offers it, strongest first."""
    merged: dict[tuple, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            key = (item["from_dataset_id"], item["from_column"], item["to_dataset_id"], item["to_column"])
            current = merged.setdefault(key, {**item, "sources": []})
            current["sources"] = sorted(set(current["sources"]) | set(item["sources"]), key=SOURCES.index)
    return sorted(merged.values(), key=lambda item: (item["from_column"], SOURCES.index(item["sources"][0])))


def verification_queries(
    source_schema: str | None,
    source_table: str,
    source_column: str,
    target_schema: str | None,
    target_table: str,
    target_column: str,
) -> dict[str, Any]:
    """The three read-only queries a check runs: the target's uniqueness, the orphan count and a few orphan values.

    The orphan queries join on the target, so they are meaningful only once the target is known to be unique.
    """
    target = table(target_table, column(target_column), schema=target_schema)
    uniqueness = select(
        func.count().label("target_rows"),
        func.count(target.c[target_column]).label("target_values"),
        func.count(func.distinct(target.c[target_column])).label("target_distinct"),
    ).select_from(target)
    source = table(source_table, column(source_column), schema=source_schema).alias("source_table")
    joined = target.alias("target_table")
    reference, key = source.c[source_column], joined.c[target_column]
    outer = source.outerjoin(joined, reference == key)
    orphans = (
        select(
            func.count(reference).label("references"),
            func.sum(case((key.is_(None), 1), else_=0)).label("orphans"),
        )
        .select_from(outer)
        .where(reference.isnot(None))
    )
    samples = (
        select(reference.label("value"))
        .distinct()
        .select_from(outer)
        .where(reference.isnot(None), key.is_(None))
        .limit(MAX_ORPHAN_SAMPLES)
    )
    return {"uniqueness": uniqueness, "orphans": orphans, "samples": samples}


def verification_result(
    uniqueness_row: dict[str, Any],
    orphan_row: dict[str, Any] | None,
    samples: list[Any],
    type_match: bool,
) -> dict[str, Any]:
    """What a check found, and whether the relationship may be approved: a unique target and comparable types.

    Orphans do not block approval; they are shown, because an inner join drops those rows.
    """
    target_values = int(uniqueness_row.get("target_values") or 0)
    target_unique = target_values > 0 and target_values == int(uniqueness_row.get("target_distinct") or 0)
    references = int((orphan_row or {}).get("references") or 0)
    orphans = int((orphan_row or {}).get("orphans") or 0)
    return {
        "target_rows": int(uniqueness_row.get("target_rows") or 0),
        "target_unique": target_unique,
        "references": references,
        "orphans": orphans,
        "orphan_ratio": round(orphans / references, 4) if references else 0.0,
        "orphan_samples": [str(value) for value in samples[:MAX_ORPHAN_SAMPLES]],
        "type_match": type_match,
        "passed": target_unique and type_match,
    }


def stored_verification(value: Any) -> dict[str, Any] | None:
    """A check stored on a contract as JSON text; anything unreadable counts as never checked."""
    if not value:
        return None
    try:
        result = json.loads(value)
    except (TypeError, ValueError):
        return None
    return result if isinstance(result, dict) else None
