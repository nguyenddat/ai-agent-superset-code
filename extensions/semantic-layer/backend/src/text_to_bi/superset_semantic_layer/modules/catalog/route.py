import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from flask import Response, current_app, request, stream_with_context
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from flask_wtf.csrf import validate_csrf
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from superset import db, security_manager
from superset.connectors.sqla.models import SqlaTable
from superset.exceptions import SupersetSecurityException
from superset.models.core import Database
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api
from wtforms import ValidationError

from ...agent_package.column_dictionary import suggest_column_dictionary_batches, suggest_dataset_dictionary
from ...core.chat_models import get_chat_model
from ...models.business_canvas import BusinessCanvas
from ...models.business_domain import BusinessDomain, business_domain_dataset
from ...models.column_dictionary import ColumnDictionary
from ...models.data_layer import DataLayer
from ...models.dataset_dictionary import DatasetDictionary
from ...models.glossary_term import GlossaryTerm, GlossaryTermAuditEvent, GlossaryTermLink, GlossaryTermRevision
from ...models.lineage_canvas import LineageCanvas
from ...models.lineage_edge import LineageEdge
from ...models.metric_contract import MetricContract
from ...models.relationship_contract import RelationshipContract
from ..business_model.service import (
    EDGE_KINDS,
    dataset_classifications,
    dataset_metrics,
    ensure_dataset_dictionaries,
    find_edge_override,
    infer_dictionary_edges,
    lineage_edges,
    serialize_domain,
    serialize_layer,
)
from ..data_dictionary.repository.repo_column_dictionary import ColumnDictionaryRepository
from ..data_dictionary.repository.repo_dataset_dictionary import DatasetDictionaryRepository
from ..glossary.service import (
    GlossaryConflictError,
    GlossaryValidationError,
    approve_revision,
    create_draft,
    glossary_link_fingerprint,
    revoke_revision,
    update_draft,
)
from ..semantic_query.catalog import build_semantic_catalog
from ..semantic_query.compiler import SemanticQueryError, compile_semantic_query
from ..semantic_query.contracts import (
    build_preview_contract,
    contract_is_approved_current,
    execute_approved_chart_query,
    metric_contract_hash,
    metric_is_eligible_for_contract,
)
from ..semantic_query.relationships import (
    RelationshipEnd,
    relationship_cardinality,
    relationship_contract_hash,
    relationship_is_approved_current,
)

logger = logging.getLogger(__name__)
DICTIONARY_FIELDS = {
    "business_term",
    "default_value",
    "display_name",
    "format",
    "is_fk",
    "is_pk",
    "is_unique",
    "nullable",
    "referenced_column",
    "referenced_dataset_id",
    "referenced_column_name",
    "unit",
}
STRING_FIELD_LIMITS = {"display_name": 255}
OPTIONAL_STRING_FIELD_LIMITS = {"format": 128, "unit": 128}
DATASET_DICTIONARY_FIELDS = {"display_name", "description", "grain", "create_column", "dataset_type", "layer_id"}
# Arbitrary key shared by every Superset worker so only one of them migrates the dictionary tables at a time.
DICTIONARY_MIGRATION_LOCK_KEY = 74_116_201
_dictionary_tables_ready = False
_dictionary_migration_failed_at: float | None = None
DICTIONARY_MIGRATION_RETRY_SECONDS = 30
CANVAS_DOMAIN_KEY = re.compile(r"^domain-(\d+|unassigned)$")
CANVAS_MAX_CELLS = 20_000
CANVAS_MAX_COORDINATE = 100_000
LINEAGE_NODE_KEY = re.compile(r"^(table|metric)-\d+$")
LINEAGE_EDGE_KEY = re.compile(r"^((flow|relation)-\d+-\d+|metric-edge-\d+)$")
LINEAGE_EDGE_STYLES = {"orthogonal", "straight", "curved"}
LINEAGE_MAX_ITEMS = 5_000
LINEAGE_MAX_POINTS = 50
SEMANTIC_QUERY_MAX_ROWS = 1_000
UTC_ZONE = timezone.utc
_dictionary_tables_lock = threading.Lock()
# A suggestion run for a dataset older than this is treated as abandoned, so a lost run cannot block the dataset.
SUGGEST_INFLIGHT_TTL_SECONDS = 15 * 60
_suggest_inflight: dict[int, float] = {}
_suggest_inflight_lock = threading.Lock()


def _csrf_protected(method):
    """Reject a state-changing request that does not carry a valid CSRF token."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return self.response(403, message="CSRF token không hợp lệ.")
        return method(self, *args, **kwargs)

    return wrapper

def _rollback_on_error(method):
    """Log an unexpected failure, discard the half-done transaction and answer with a plain 500."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            logger.exception("%s failed", method.__name__)
            db.session.rollback()
            return self.response_500(message="Could not save the change.")

    return wrapper


def _semantic_query_row_cap() -> int:
    """Use the deployment cap without accepting a client-selected result limit."""
    configured = current_app.config.get("SEMANTIC_QUERY_MAX_ROWS", SEMANTIC_QUERY_MAX_ROWS)
    return min(max(int(configured), 1), SEMANTIC_QUERY_MAX_ROWS)


def _is_superset_access_error(error: Exception) -> bool:
    return any(word in error.__class__.__name__.lower() for word in ("access", "forbidden", "permission", "security"))


def _claim_suggestion(dataset_id: int) -> bool:
    """Mark a dataset as being suggested; False when another run for it is still active."""
    now = time.monotonic()
    with _suggest_inflight_lock:
        started = _suggest_inflight.get(dataset_id)
        if started is not None and now - started < SUGGEST_INFLIGHT_TTL_SECONDS:
            return False
        _suggest_inflight[dataset_id] = now
        return True


def _release_suggestion(dataset_id: int) -> None:
    with _suggest_inflight_lock:
        _suggest_inflight.pop(dataset_id, None)


def _column_metadata_values(column: Any) -> dict[str, Any]:
    column_name = str(column.column_name)
    return {
        "column_name": column_name,
        "display_name": str(getattr(column, "verbose_name", None) or column_name)[:255],
        "data_type": str(getattr(column, "type", None) or "UNKNOWN")[:128],
        "nullable": bool(getattr(column, "nullable", True)),
        "default_value": None,
        "is_pk": False,
        "is_fk": False,
        "referenced_column": None,
        "is_unique": False,
        "unit": None,
        "format": None,
        "business_term": None,
    }


def _validate_dictionary_payload(payload: Any, actual_column_names: set[str], dataset_id: int) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("columns"), list):
        raise TypeError("Request body must contain a columns array.")

    normalized: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, item in enumerate(payload["columns"]):
        if not isinstance(item, dict):
            raise TypeError(f"columns[{index}] must be an object.")
        unknown_fields = set(item) - DICTIONARY_FIELDS - {"column_name"}
        if unknown_fields:
            raise ValueError(f"columns[{index}] contains unsupported fields: {', '.join(sorted(unknown_fields))}.")
        column_name = item.get("column_name")
        if not isinstance(column_name, str) or not column_name:
            raise ValueError(f"columns[{index}].column_name must be a non-empty string.")
        if column_name not in actual_column_names:
            raise ValueError(f"Unknown dataset column: {column_name}.")
        if column_name in seen_names:
            raise ValueError(f"Duplicate dataset column: {column_name}.")
        seen_names.add(column_name)

        values = {"column_name": column_name}
        for field, max_length in STRING_FIELD_LIMITS.items():
            if field not in item:
                continue
            value = item[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"columns[{index}].{field} must be a non-empty string.")
            if len(value) > max_length:
                raise ValueError(f"columns[{index}].{field} must be at most {max_length} characters.")
            values[field] = value
        for field in ("default_value", "business_term"):
            if field in item:
                value = item[field]
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"columns[{index}].{field} must be a string or null.")
                if field == "business_term" and value is not None and not value.strip():
                    value = None
                values[field] = value
        for field in ("nullable", "is_pk", "is_fk", "is_unique"):
            if field in item:
                if not isinstance(item[field], bool):
                    raise ValueError(f"columns[{index}].{field} must be a boolean.")
                values[field] = item[field]
        if "referenced_dataset_id" in item or "referenced_column_name" in item:
            referenced_dataset_id = item.get("referenced_dataset_id")
            referenced_column_name = item.get("referenced_column_name")
            if referenced_dataset_id is None and referenced_column_name is None:
                values["referenced_dataset_id"] = None
                values["referenced_column_name"] = None
            elif (
                isinstance(referenced_dataset_id, bool)
                or not isinstance(referenced_dataset_id, int)
                or not isinstance(referenced_column_name, str)
                or not referenced_column_name
            ):
                raise ValueError(f"columns[{index}] must specify both a referenced dataset and column.")
            else:
                referenced_dataset = db.session.get(SqlaTable, referenced_dataset_id)
                if referenced_dataset is None:
                    raise ValueError(f"Unknown referenced dataset: {referenced_dataset_id}.")
                referenced_column_names = {str(column.column_name) for column in referenced_dataset.columns}
                if referenced_column_name not in referenced_column_names:
                    raise ValueError(f"Unknown referenced column: {referenced_column_name}.")
                if referenced_dataset_id == dataset_id and referenced_column_name == column_name:
                    raise ValueError("A column cannot reference itself.")
                values["referenced_dataset_id"] = referenced_dataset_id
                values["referenced_column_name"] = referenced_column_name
        elif "referenced_column" in item:
            referenced_column = item["referenced_column"]
            if referenced_column is not None and not isinstance(referenced_column, str):
                raise ValueError(f"columns[{index}].referenced_column must be a column name or null.")
            if referenced_column == column_name:
                raise ValueError("A column cannot reference itself.")
            if referenced_column is not None and referenced_column not in actual_column_names:
                raise ValueError(f"Unknown referenced column: {referenced_column}.")
            values["referenced_dataset_id"] = dataset_id if referenced_column else None
            values["referenced_column_name"] = referenced_column
        for field in ("unit", "format"):
            if field in item:
                value = item[field]
                if value is not None and (
                    not isinstance(value, str) or len(value) > OPTIONAL_STRING_FIELD_LIMITS[field]
                ):
                    raise ValueError(f"columns[{index}].{field} must be a string of at most 128 characters or null.")
                values[field] = value if value is None or value.strip() else None
        normalized.append(values)
    return normalized


def _serialize_dictionary(
    dataset: SqlaTable,
    dictionary: DatasetDictionary,
    columns: list[Any],
) -> dict[str, Any]:
    records = {column.column_name: column for column in columns}
    # One query per kind of record, not one per referenced column.
    referenced_ids = {row.referenced_column for row in columns if row.referenced_column is not None}
    references_by_id = (
        {row.id: row for row in db.session.query(ColumnDictionary).filter(ColumnDictionary.id.in_(referenced_ids))}
        if referenced_ids
        else {}
    )
    referenced_dataset_ids = {row.dataset_id for row in references_by_id.values()}
    datasets_by_id = (
        {row.id: row for row in db.session.query(SqlaTable).filter(SqlaTable.id.in_(referenced_dataset_ids))}
        if referenced_dataset_ids
        else {}
    )

    def reference_values(row: ColumnDictionary) -> dict[str, Any]:
        referenced = references_by_id.get(row.referenced_column)
        referenced_dataset = datasets_by_id.get(referenced.dataset_id) if referenced else None
        database_name = getattr(getattr(referenced_dataset, "database", None), "database_name", None)
        schema_name = getattr(referenced_dataset, "schema", None) if referenced_dataset else None
        table_name = getattr(referenced_dataset, "table_name", None) if referenced_dataset else None
        label = ".".join(part for part in (database_name, schema_name, table_name) if part)
        return {
            "referenced_column": referenced.column_name if referenced else None,
            "referenced_dataset_id": referenced.dataset_id if referenced else None,
            "referenced_column_name": referenced.column_name if referenced else None,
            "referenced_dataset_label": label or (table_name if referenced else None),
        }
    return {
        "dataset_id": dataset.id,
        "dataset_name": dataset.table_name,
        "display_name": dictionary.display_name,
        "description": dictionary.description,
        "grain": dictionary.grain,
        "create_column": dictionary.create_column,
        "dataset_type": dictionary.dataset_type,
        "layer_id": dictionary.layer_id,
        "read_only": False,
        "columns": [
            {
                "id": records[actual.column_name].id,
                "column_name": actual.column_name,
                "display_name": records[actual.column_name].display_name,
                "data_type": str(getattr(actual, "type", None) or "UNKNOWN")[:128],
                "nullable": records[actual.column_name].nullable,
                "default_value": records[actual.column_name].default_value,
                "is_pk": records[actual.column_name].is_pk,
                "is_fk": records[actual.column_name].is_fk,
                **reference_values(records[actual.column_name]),
                "is_unique": records[actual.column_name].is_unique,
                "unit": records[actual.column_name].unit,
                "format": records[actual.column_name].format,
                "business_term": records[actual.column_name].business_term,
            }
            for actual in dataset.columns
        ],
    }


def _sse_event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _seed_dictionary_columns(
    dataset: SqlaTable,
    repository: ColumnDictionaryRepository,
) -> list[ColumnDictionary]:
    existing = {column.column_name: column for column in repository.list_for_dataset(dataset.id)}
    actual_names = {str(column.column_name) for column in dataset.columns}
    # Columns dropped or renamed in Superset leave dictionary rows behind; references to them are cleared by the FK.
    for stale_name in [name for name in existing if name not in actual_names]:
        repository.delete(existing.pop(stale_name))
    for actual_column in dataset.columns:
        column_name = str(actual_column.column_name)
        if column_name not in existing:
            values = _column_metadata_values(actual_column)
            existing[column_name] = repository.add(ColumnDictionary(dataset_id=dataset.id, **values))
    return list(existing.values())


def _get_or_create_dataset_dictionary(dataset: SqlaTable, repository: DatasetDictionaryRepository) -> DatasetDictionary:
    record = repository.get(dataset.id)
    if record is None:
        record = repository.add(
            DatasetDictionary(
                id=dataset.id,
                dataset_name=dataset.table_name,
                display_name=dataset.table_name,
                description=dataset.description,
            )
        )
    return record


def _seed_dictionary(dataset: SqlaTable) -> None:
    """Sync a dataset's dictionary rows with its Superset columns and commit them.

    Committing here leaves no transaction open for what follows. Two requests seeding the same new dataset collide on
    the unique keys; the loser rolls back and retries, which then finds the rows the winner created.
    """
    for attempt in range(2):
        try:
            _get_or_create_dataset_dictionary(dataset, DatasetDictionaryRepository(db.session))
            _seed_dictionary_columns(dataset, ColumnDictionaryRepository(db.session))
            db.session.commit()
            return
        except IntegrityError:
            db.session.rollback()
            if attempt:
                raise


def _ensure_dictionary_tables():
    """Run the dictionary table migration once per process.

    The migration takes ACCESS EXCLUSIVE locks, so concurrent dictionary requests must not run it in parallel.
    """
    global _dictionary_tables_ready, _dictionary_migration_failed_at
    if _dictionary_tables_ready:
        return
    with _dictionary_tables_lock:
        if _dictionary_tables_ready:
            return
        # A failing migration holds ACCESS EXCLUSIVE locks while it runs, so requests must not retry it back to back.
        failed_at = _dictionary_migration_failed_at
        if failed_at is not None and time.monotonic() - failed_at < DICTIONARY_MIGRATION_RETRY_SECONDS:
            raise RuntimeError("The dictionary table migration failed recently; see the earlier error in the log.")
        try:
            if db.engine.dialect.name != "postgresql":
                _migrate_dictionary_tables()
            else:
                with db.engine.connect() as lock_connection:
                    lock_connection.execute(
                        text("SELECT pg_advisory_lock(:key)"), {"key": DICTIONARY_MIGRATION_LOCK_KEY}
                    )
                    try:
                        _migrate_dictionary_tables()
                    finally:
                        lock_connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": DICTIONARY_MIGRATION_LOCK_KEY}
                        )
        except Exception:
            _dictionary_migration_failed_at = time.monotonic()
            logger.exception("Dictionary migration failed; next attempt in %ss", DICTIONARY_MIGRATION_RETRY_SECONDS)
            raise
        _dictionary_migration_failed_at = None
        _dictionary_tables_ready = True


def _migrate_dictionary_tables():
    """Create extension tables and upgrade the earlier column dictionary schema.

    Creating tables, adding columns and seeding are portable. Upgrading installs that predate the current column
    dictionary schema renames and alters constraints, which only PostgreSQL installations ever needed.
    """
    postgres = db.engine.dialect.name == "postgresql"
    inspector = inspect(db.engine)
    if postgres and inspector.has_table(ColumnDictionary.__tablename__):
        columns = {column["name"] for column in inspector.get_columns(ColumnDictionary.__tablename__)}
        if "table_id" in columns and "dataset_id" not in columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE text_to_bi_column_dictionary "
                        "RENAME COLUMN table_id TO dataset_id"
                    )
                )
                unique_constraints = {
                    constraint["name"]
                    for constraint in inspect(connection).get_unique_constraints(
                        ColumnDictionary.__tablename__
                    )
                }
                old_constraint = "uq_text_to_bi_column_table_display_name"
                if old_constraint in unique_constraints:
                    connection.execute(
                        text(
                            "ALTER TABLE text_to_bi_column_dictionary "
                            "RENAME CONSTRAINT uq_text_to_bi_column_table_display_name "
                            "TO uq_text_to_bi_column_dataset_display_name"
                        )
                    )

    # Layers come first: dataset dictionaries reference them.
    DataLayer.__table__.create(bind=db.engine, checkfirst=True)
    DatasetDictionary.__table__.create(bind=db.engine, checkfirst=True)
    ColumnDictionary.__table__.create(bind=db.engine, checkfirst=True)
    BusinessDomain.__table__.create(bind=db.engine, checkfirst=True)
    business_domain_dataset.create(bind=db.engine, checkfirst=True)
    LineageEdge.__table__.create(bind=db.engine, checkfirst=True)
    BusinessCanvas.__table__.create(bind=db.engine, checkfirst=True)
    LineageCanvas.__table__.create(bind=db.engine, checkfirst=True)
    MetricContract.__table__.create(bind=db.engine, checkfirst=True)
    RelationshipContract.__table__.create(bind=db.engine, checkfirst=True)
    # Glossary parent tables must exist before immutable revisions, links, and audit evidence.
    GlossaryTerm.__table__.create(bind=db.engine, checkfirst=True)
    GlossaryTermRevision.__table__.create(bind=db.engine, checkfirst=True)
    GlossaryTermLink.__table__.create(bind=db.engine, checkfirst=True)
    GlossaryTermAuditEvent.__table__.create(bind=db.engine, checkfirst=True)

    with db.engine.begin() as connection:
        contract_columns = {column["name"] for column in inspect(connection).get_columns(MetricContract.__tablename__)}
        if "revoker_id" not in contract_columns:
            revoker_column = "INTEGER REFERENCES ab_user (id) ON DELETE SET NULL" if postgres else "INTEGER"
            connection.execute(text(f"ALTER TABLE text_to_bi_metric_contract ADD COLUMN revoker_id {revoker_column}"))
        if "revoked_at" not in contract_columns:
            connection.execute(text("ALTER TABLE text_to_bi_metric_contract ADD COLUMN revoked_at TIMESTAMP WITH TIME ZONE"))
        if postgres:
            contract_constraints = inspect(connection).get_foreign_keys(MetricContract.__tablename__)
            has_revoker_fk = any(
                constraint.get("constrained_columns") == ["revoker_id"]
                and constraint.get("referred_table") == "ab_user"
                and constraint.get("referred_columns") == ["id"]
                for constraint in contract_constraints
            )
            if not has_revoker_fk:
                connection.execute(
                    text(
                        "ALTER TABLE text_to_bi_metric_contract "
                        "ADD CONSTRAINT fk_text_to_bi_metric_contract_revoker "
                        "FOREIGN KEY (revoker_id) REFERENCES ab_user (id) ON DELETE SET NULL"
                    )
                )
        contract_indexes = {index["name"] for index in inspect(connection).get_indexes(MetricContract.__tablename__)}
        if "ix_text_to_bi_metric_contract_revoker_id" not in contract_indexes:
            connection.execute(text("CREATE INDEX ix_text_to_bi_metric_contract_revoker_id ON text_to_bi_metric_contract (revoker_id)"))

    with db.engine.begin() as connection:
        layer_columns = {column["name"] for column in inspect(connection).get_columns(DataLayer.__tablename__)}
        # Layers created before levels existed flowed one after another, so each keeps a level of its own.
        if "level" not in layer_columns:
            connection.execute(text("ALTER TABLE text_to_bi_data_layer ADD COLUMN level INTEGER NOT NULL DEFAULT 0"))
            layer_ids = connection.execute(text("SELECT id FROM text_to_bi_data_layer ORDER BY sort_order, id")).scalars()
            for position, layer_id in enumerate(list(layer_ids)):
                connection.execute(
                    text("UPDATE text_to_bi_data_layer SET level = :level WHERE id = :id"),
                    {"level": position, "id": layer_id},
                )

    with db.engine.begin() as connection:
        edge_columns = {column["name"] for column in inspect(connection).get_columns(LineageEdge.__tablename__)}
        # Rows created before is_manual existed were all manual edges or hidden overrides.
        for column_name, column_type in (("is_manual", "BOOLEAN NOT NULL DEFAULT TRUE"), ("color", "VARCHAR(16)")):
            if column_name not in edge_columns:
                connection.execute(text(f"ALTER TABLE text_to_bi_lineage_edge ADD COLUMN {column_name} {column_type}"))

    with db.engine.begin() as connection:
        dataset_columns = {
            column["name"] for column in inspect(connection).get_columns(DatasetDictionary.__tablename__)
        }
        dataset_columns_to_add = (
            ("description", "TEXT"),
            ("grain", "TEXT"),
            ("create_column", "VARCHAR(255)"),
            ("dataset_type", "VARCHAR(32)"),
            ("layer_id", "INTEGER REFERENCES text_to_bi_data_layer (id) ON DELETE SET NULL"),
        )
        for column_name, column_type in dataset_columns_to_add:
            if column_name not in dataset_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE text_to_bi_dataset_dictionary ADD COLUMN {column_name} {column_type}"
                    )
                )

    if postgres:
        with db.engine.begin() as connection:
            columns = {
                column["name"]: column for column in inspect(connection).get_columns(ColumnDictionary.__tablename__)
            }
            if "column_name" not in columns:
                connection.execute(
                    text("ALTER TABLE text_to_bi_column_dictionary ADD COLUMN column_name VARCHAR(255)")
                )
            if "column_name" not in columns or columns["column_name"]["nullable"]:
                connection.execute(
                    text(
                        "UPDATE text_to_bi_column_dictionary "
                        "SET column_name = display_name WHERE column_name IS NULL"
                    )
                )
                connection.execute(
                    text("ALTER TABLE text_to_bi_column_dictionary ALTER COLUMN column_name SET NOT NULL")
                )

            unique_constraints = inspect(connection).get_unique_constraints(ColumnDictionary.__tablename__)
            has_column_name_constraint = any(
                constraint.get("column_names") == ["dataset_id", "column_name"]
                for constraint in unique_constraints
            )
            preparer = connection.dialect.identifier_preparer
            for constraint in unique_constraints:
                if constraint.get("column_names") == ["dataset_id", "display_name"] and constraint.get("name"):
                    connection.execute(
                        text(
                            "ALTER TABLE text_to_bi_column_dictionary DROP CONSTRAINT "
                            f"{preparer.quote(constraint['name'])}"
                        )
                    )
            if not has_column_name_constraint:
                connection.execute(
                    text(
                        "ALTER TABLE text_to_bi_column_dictionary "
                        "ADD CONSTRAINT uq_text_to_bi_column_dataset_column_name "
                        "UNIQUE (dataset_id, column_name)"
                    )
                )

    with db.engine.begin() as connection:
        # Seed a basic dictionary record for every existing Superset dataset.
        connection.execute(
            text(
                "INSERT INTO text_to_bi_dataset_dictionary "
                "(id, dataset_name, display_name, description) "
                "SELECT id, table_name, table_name, description "
                "FROM tables WHERE id NOT IN (SELECT id FROM text_to_bi_dataset_dictionary)"
            )
        )

        if postgres:
            constraints = inspect(connection).get_foreign_keys(ColumnDictionary.__tablename__)
            dataset_constraints = [
                constraint
                for constraint in constraints
                if constraint.get("constrained_columns") == ["dataset_id"]
            ]
            has_dictionary_fk = any(
                constraint.get("referred_table") == DatasetDictionary.__tablename__
                and constraint.get("referred_columns") == ["id"]
                for constraint in dataset_constraints
            )
            preparer = connection.dialect.identifier_preparer
            for constraint in dataset_constraints:
                if constraint.get("referred_table") != DatasetDictionary.__tablename__:
                    constraint_name = preparer.quote(constraint["name"])
                    connection.execute(
                        text(
                            f"ALTER TABLE text_to_bi_column_dictionary "
                            f"DROP CONSTRAINT {constraint_name}"
                        )
                    )
            if not has_dictionary_fk:
                connection.execute(
                    text(
                        "ALTER TABLE text_to_bi_column_dictionary "
                        "ADD CONSTRAINT fk_text_to_bi_column_dataset_dictionary "
                        "FOREIGN KEY (dataset_id) "
                        "REFERENCES text_to_bi_dataset_dictionary (id) ON DELETE CASCADE"
                    )
                )

            indexes = {index["name"] for index in inspect(connection).get_indexes(ColumnDictionary.__tablename__)}
            old_index = "ix_text_to_bi_column_dictionary_table_id"
            if old_index in indexes:
                old_index_name = preparer.quote(old_index)
                connection.execute(
                    text(
                        f"ALTER INDEX {old_index_name} "
                        "RENAME TO ix_text_to_bi_column_dictionary_dataset_id"
                    )
                )


@api(
    id="text_to_bi_semantic_layer_api",
    name="Text to BI Semantic Layer API",
    description="Admin API for the Semantic Layer extension.",
    resource_name="semantic-layer",
)
class SemanticLayerAPI(RestApi):
    openapi_spec_tag = "Text to BI Semantic Layer"
    class_permission_name = "text_to_bi_semantic_layer_api"

    @staticmethod
    def _is_admin():
        return bool(
            getattr(current_user, "is_authenticated", False)
            and any(role.name == "Admin" for role in getattr(current_user, "roles", []))
        )

    @staticmethod
    def _can_preview_semantic_query(dataset: SqlaTable) -> bool:
        """Use Superset's native datasource permission gate for previews and execution."""
        try:
            security_manager.raise_for_access(datasource=dataset)
        except SupersetSecurityException:
            return False
        return True

    _can_access_semantic_query_dataset = _can_preview_semantic_query

    @staticmethod
    def _dataset_metric(dataset: SqlaTable, metric_id: int):
        """Resolve only a metric actually attached to this dataset."""
        return next((metric for metric in dataset.metrics if metric.id == metric_id), None)

    @staticmethod
    def _contract_for(dataset_id: int, metric_id: int):
        return (
            db.session.query(MetricContract)
            .filter(MetricContract.dataset_id == dataset_id, MetricContract.metric_id == metric_id)
            .one_or_none()
        )

    @staticmethod
    def _serialize_metric_contract(contract: MetricContract, dataset: SqlaTable, metric: Any) -> dict[str, Any]:
        """Do not expose expression/hash in execution-facing responses."""
        return {
            "id": contract.id,
            "dataset_id": contract.dataset_id,
            "metric_id": contract.metric_id,
            "metric_name": metric.metric_name,
            "status": contract.status,
            "owner_id": contract.owner_id,
            "approver_id": contract.approver_id,
            "approved_at": contract.approved_at.isoformat() if contract.approved_at else None,
            "revoker_id": contract.revoker_id,
            "revoked_at": contract.revoked_at.isoformat() if contract.revoked_at else None,
            "current": contract_is_approved_current(contract, dataset, metric),
        }

    @staticmethod
    def _fk_entry(dataset_id: int, column_id: int) -> ColumnDictionary | None:
        return (
            db.session.query(ColumnDictionary)
            .filter(ColumnDictionary.id == column_id, ColumnDictionary.dataset_id == dataset_id)
            .one_or_none()
        )

    @staticmethod
    def _relationship_ends(fk_entry: ColumnDictionary) -> tuple[RelationshipEnd, RelationshipEnd] | None:
        """Resolve a dictionary FK to live datasets, retaining composite-key information."""
        if not fk_entry.referenced_column:
            return None
        target_entry = db.session.get(ColumnDictionary, fk_entry.referenced_column)
        if target_entry is None:
            return None
        source = db.session.get(SqlaTable, fk_entry.dataset_id)
        target = db.session.get(SqlaTable, target_entry.dataset_id)
        if source is None or target is None:
            return None

        def end(dataset: SqlaTable, entry: ColumnDictionary) -> RelationshipEnd:
            live_names = {str(column.column_name) for column in dataset.columns}
            pk_count = sum(
                1
                for row in db.session.query(ColumnDictionary).filter(
                    ColumnDictionary.dataset_id == dataset.id, ColumnDictionary.is_pk.is_(True)
                )
                if row.column_name in live_names
            )
            return RelationshipEnd(dataset=dataset, entry=entry, pk_count=pk_count)

        return end(source, fk_entry), end(target, target_entry)

    @staticmethod
    def _relationship_contract_for(from_dataset_id: int, from_column: str) -> RelationshipContract | None:
        return (
            db.session.query(RelationshipContract)
            .filter(
                RelationshipContract.from_dataset_id == from_dataset_id,
                RelationshipContract.from_column == from_column,
            )
            .one_or_none()
        )

    @staticmethod
    def _serialize_relationship_contract(
        contract: RelationshipContract, source: RelationshipEnd, target: RelationshipEnd
    ) -> dict[str, Any]:
        return {
            "id": contract.id,
            "from_dataset_id": contract.from_dataset_id,
            "from_column": contract.from_column,
            "to_dataset_id": contract.to_dataset_id,
            "to_column": contract.to_column,
            "cardinality": contract.cardinality,
            "status": contract.status,
            "owner_id": contract.owner_id,
            "approver_id": contract.approver_id,
            "approved_at": contract.approved_at.isoformat() if contract.approved_at else None,
            "revoker_id": contract.revoker_id,
            "revoked_at": contract.revoked_at.isoformat() if contract.revoked_at else None,
            "current": relationship_is_approved_current(contract, source, target),
            "executable": False,
        }

    @expose("/access", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_access(self):
        """Return whether the authenticated user is a Superset administrator."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        return self.response(200, is_admin=True)

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/candidate", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def create_metric_contract_candidate(self, dataset_id: int, metric_id: int):
        """Snapshot a saved metric for an administrator to review."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        dataset = db.session.get(SqlaTable, dataset_id)
        if dataset is None:
            return self.response(404, message="Dataset not found.")
        metric = self._dataset_metric(dataset, metric_id)
        if metric is None:
            return self.response(404, message="Metric not found in this dataset.")
        if not metric_is_eligible_for_contract(dataset, metric):
            return self.response_400(message="Metric must be a simple aggregate over one active physical-table column.")
        contract = self._contract_for(dataset_id, metric_id)
        if contract is not None and contract.status == "approved" and contract_is_approved_current(contract, dataset, metric):
            return self.response(409, message="Revoke the current approved contract before creating another candidate.")
        if contract is None:
            contract = MetricContract(dataset_id=dataset_id, metric_id=metric_id)
            db.session.add(contract)
            contract.owner_id = current_user.id
        contract.metric_name = metric.metric_name
        contract.expression = metric.expression
        contract.expression_hash = metric_contract_hash(dataset, metric)
        contract.status = "candidate"
        contract.approver_id = None
        contract.approved_at = None
        contract.revoker_id = None
        contract.revoked_at = None
        db.session.commit()
        return self.response(201, contract=self._serialize_metric_contract(contract, dataset, metric))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def approve_metric_contract(self, dataset_id: int, metric_id: int):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        dataset = db.session.get(SqlaTable, dataset_id)
        if dataset is None:
            return self.response(404, message="Dataset not found.")
        metric = self._dataset_metric(dataset, metric_id)
        contract = self._contract_for(dataset_id, metric_id) if metric else None
        if metric is None or contract is None:
            return self.response(404, message="Metric contract not found in this dataset.")
        if contract.status != "candidate":
            return self.response_400(message="Only a candidate metric contract can be approved.")
        if not metric_is_eligible_for_contract(dataset, metric):
            return self.response_400(message="Metric must be a simple aggregate over one active physical-table column.")
        if contract.expression_hash != metric_contract_hash(dataset, metric):
            return self.response_400(message="Metric changed; create a new candidate before approval.")
        contract.status = "approved"
        contract.approver_id = current_user.id
        contract.approved_at = datetime.now(tz=timezone.utc)
        db.session.commit()
        return self.response(200, contract=self._serialize_metric_contract(contract, dataset, metric))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def revoke_metric_contract(self, dataset_id: int, metric_id: int):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        dataset = db.session.get(SqlaTable, dataset_id)
        if dataset is None:
            return self.response(404, message="Dataset not found.")
        metric = self._dataset_metric(dataset, metric_id)
        contract = self._contract_for(dataset_id, metric_id) if metric else None
        if metric is None or contract is None:
            return self.response(404, message="Metric contract not found in this dataset.")
        contract.status = "revoked"
        contract.revoker_id = current_user.id
        contract.revoked_at = datetime.now(tz=timezone.utc)
        db.session.commit()
        return self.response(200, contract=self._serialize_metric_contract(contract, dataset, metric))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/semantic-query/execute", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @_csrf_protected
    @_rollback_on_error
    def execute_metric_contract(self, dataset_id: int, metric_id: int):
        """Execute a current approved metric exclusively through Superset ChartData."""
        _ensure_dictionary_tables()
        dataset = db.session.get(SqlaTable, dataset_id)
        if dataset is None:
            return self.response(404, message="Dataset not found.")
        if not self._can_access_semantic_query_dataset(dataset):
            return self.response(403, message="Dataset and database access required.")
        metric = self._dataset_metric(dataset, metric_id)
        contract = self._contract_for(dataset_id, metric_id) if metric else None
        if metric is None:
            return self.response(403, message="A current approved metric contract is required.")
        body = request.get_json(silent=True)
        try:
            # validate() is Superset's datasource/RLS permission gate and runs as
            # the request's current_user; this route never compiles or runs SQL.
            from superset.charts.schemas import ChartDataQueryContextSchema
            from superset.commands.chart.data.get_data_command import ChartDataCommand

            def run_chart(payload):
                command = ChartDataCommand(ChartDataQueryContextSchema().load(payload))
                command.validate()
                return command.run()["queries"][0]

            result = execute_approved_chart_query(
                contract, dataset, metric, body, _semantic_query_row_cap(), run_chart
            )
        except PermissionError as ex:
            db.session.rollback()
            return self.response(403, message=str(ex))
        except ValueError as ex:
            db.session.rollback()
            return self.response_400(message=str(ex))
        except Exception as ex:
            db.session.rollback()
            if _is_superset_access_error(ex):
                return self.response(403, message="Superset denied metric execution.")
            logger.exception("Superset ChartData metric execution failed")
            return self.response_500(message="Metric execution was rejected by Superset.")
        if result.get("error"):
            return self.response_500(message="Metric execution failed.")
        rows = result.get("data", [])
        return self.response(
            200,
            columns=result.get("colnames", []),
            rows=rows[:_semantic_query_row_cap()],
            row_count=min(len(rows), _semantic_query_row_cap()),
            truncated=len(rows) > _semantic_query_row_cap(),
        )

    @expose("/dataset/<int:dataset_id>/semantic-query/preview", methods=("POST",))
    @protect()
    @permission_name("read")
    @_csrf_protected
    def preview_semantic_query(self, dataset_id: int):
        """Compile, but never execute, a one-dataset semantic query preview."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        dataset = db.session.get(SqlaTable, dataset_id)
        if dataset is None:
            return self.response(404, message="Dataset not found.")
        if not self._can_preview_semantic_query(dataset):
            return self.response(403, message="Dataset and database access required.")
        query_request = request.get_json(silent=True)
        if not isinstance(query_request, dict):
            return self.response_400(message="Request body must be a JSON object.")

        dictionary_columns = db.session.query(ColumnDictionary).filter(ColumnDictionary.dataset_id == dataset_id).all()
        contract = build_preview_contract(dataset, dictionary_columns)
        try:
            preview = compile_semantic_query(
                contract["dataset"],
                [{**metric, "approved": metric["eligible_for_preview"]} for metric in contract["metrics"]],
                [{**dimension, "approved": dimension["eligible_for_preview"]} for dimension in contract["dimensions"]],
                query_request,
            )
        except SemanticQueryError as ex:
            return self.response_400(message=str(ex))
        preview["provenance"]["contract_source"] = contract["contract_source"]
        preview["provenance"]["execution"] = "not_executed"
        return self.response(200, preview=preview)

    def _relationship_contract_context(self, dataset_id: int, column_id: int):
        entry = self._fk_entry(dataset_id, column_id)
        if entry is None:
            return None, None, self.response(404, message="Foreign-key dictionary column not found in this dataset.")
        ends = self._relationship_ends(entry)
        if ends is None:
            return None, None, self.response_400(message="The referenced dictionary column or dataset no longer exists.")
        source, target = ends
        try:
            relationship_cardinality(source, target)
        except ValueError as ex:
            return None, None, self.response_400(message=str(ex))
        return source, target, None

    @expose("/dataset/<int:dataset_id>/relationships/<int:column_id>/contract/candidate", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def create_relationship_contract_candidate(self, dataset_id: int, column_id: int):
        """Snapshot an eligible declared FK relationship for administrator approval."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        source, target, error = self._relationship_contract_context(dataset_id, column_id)
        if error is not None:
            return error
        cardinality = relationship_cardinality(source, target)
        contract = self._relationship_contract_for(source.dataset.id, source.entry.column_name)
        if contract is not None and relationship_is_approved_current(contract, source, target):
            return self.response(409, message="Revoke the current approved contract before creating another candidate.")
        if contract is None:
            contract = RelationshipContract(from_dataset_id=source.dataset.id, from_column=source.entry.column_name)
            contract.owner_id = current_user.id
            db.session.add(contract)
        contract.to_dataset_id = target.dataset.id
        contract.to_column = target.entry.column_name
        contract.cardinality = cardinality
        contract.contract_hash = relationship_contract_hash(source, target, cardinality)
        contract.approver_id = None
        contract.approved_at = None
        contract.revoker_id = None
        contract.revoked_at = None
        contract.status = "candidate"
        db.session.commit()
        return self.response(201, contract=self._serialize_relationship_contract(contract, source, target))

    @expose("/dataset/<int:dataset_id>/relationships/<int:column_id>/contract/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def approve_relationship_contract(self, dataset_id: int, column_id: int):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        source, target, error = self._relationship_contract_context(dataset_id, column_id)
        if error is not None:
            return error
        contract = self._relationship_contract_for(source.dataset.id, source.entry.column_name)
        if contract is None:
            return self.response(404, message="Relationship contract not found for this foreign key.")
        if contract.status != "candidate":
            return self.response_400(message="Only a candidate relationship contract can be approved.")
        cardinality = relationship_cardinality(source, target)
        if contract.contract_hash != relationship_contract_hash(source, target, cardinality):
            return self.response_400(message="Relationship changed; create a new candidate before approval.")
        contract.status = "approved"
        contract.approver_id = current_user.id
        contract.approved_at = datetime.now(timezone.utc)
        db.session.commit()
        return self.response(200, contract=self._serialize_relationship_contract(contract, source, target))

    @expose("/dataset/<int:dataset_id>/relationships/<int:column_id>/contract/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def revoke_relationship_contract(self, dataset_id: int, column_id: int):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        entry = self._fk_entry(dataset_id, column_id)
        contract = self._relationship_contract_for(dataset_id, entry.column_name) if entry is not None else None
        contract_id = request.args.get("contract_id", type=int)
        if contract_id is not None:
            candidate = db.session.get(RelationshipContract, contract_id)
            # A contract ID is only an alternate key for this route's relationship when
            # the path FK entry independently binds it to the same source column. If the
            # entry is gone, the request no longer carries enough information to prove
            # which relationship the caller intended, even when the ID belongs to this dataset.
            if (
                candidate is None
                or entry is None
                or candidate.from_dataset_id != dataset_id
                or candidate.from_column != entry.column_name
                or (contract is not None and candidate.id != contract.id)
            ):
                return self.response(404, message="Relationship contract not found for this foreign key.")
            contract = candidate
        if contract is None:
            return self.response(404, message="Relationship contract not found for this foreign key.")
        contract.status = "revoked"
        contract.revoker_id = current_user.id
        contract.revoked_at = datetime.now(timezone.utc)
        db.session.commit()
        ends = self._relationship_ends(entry) if entry is not None else None
        if ends is None:
            return self.response(
                200,
                contract={
                    "id": contract.id,
                    "from_dataset_id": contract.from_dataset_id,
                    "from_column": contract.from_column,
                    "to_dataset_id": contract.to_dataset_id,
                    "to_column": contract.to_column,
                    "cardinality": contract.cardinality,
                    "status": contract.status,
                    "owner_id": contract.owner_id,
                    "approver_id": contract.approver_id,
                    "approved_at": contract.approved_at.isoformat() if contract.approved_at else None,
                    "revoker_id": contract.revoker_id,
                    "revoked_at": contract.revoked_at.isoformat() if contract.revoked_at else None,
                    "current": False,
                    "executable": False,
                },
            )
        return self.response(200, contract=self._serialize_relationship_contract(contract, *ends))

    @expose("/semantic-catalog", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def semantic_catalog(self):
        """List current approved semantic metadata filtered by caller datasource access."""
        _ensure_dictionary_tables()
        metric_contracts = db.session.query(MetricContract).filter(MetricContract.status == "approved").all()
        relationship_contracts = db.session.query(RelationshipContract).filter(RelationshipContract.status == "approved").all()
        dataset_ids = {contract.dataset_id for contract in metric_contracts}
        dataset_ids.update(contract.from_dataset_id for contract in relationship_contracts)
        dataset_ids.update(contract.to_dataset_id for contract in relationship_contracts)
        datasets = {
            dataset.id: dataset for dataset in db.session.query(SqlaTable).filter(SqlaTable.id.in_(dataset_ids)).all()
        } if dataset_ids else {}
        relationships = []
        for contract in relationship_contracts:
            entry = (
                db.session.query(ColumnDictionary)
                .filter(
                    ColumnDictionary.dataset_id == contract.from_dataset_id,
                    ColumnDictionary.column_name == contract.from_column,
                )
                .one_or_none()
            )
            if entry is None:
                continue
            ends = self._relationship_ends(entry)
            if ends is not None:
                relationships.append((contract, *ends))
        catalog = build_semantic_catalog(
            datasets, metric_contracts, relationships, self._can_access_semantic_query_dataset, _semantic_query_row_cap()
        )
        return self.response(200, **catalog)

    @expose("/datasets/reference-options", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_reference_options(self):
        """List Superset datasets and columns for foreign key references."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        datasets = db.session.query(SqlaTable).order_by(SqlaTable.table_name, SqlaTable.id).all()
        # Key flags declared in the data dictionary let the picker offer key columns as FK targets first.
        key_flags: dict[int, dict[str, dict[str, bool]]] = {}
        for row in db.session.query(ColumnDictionary).filter(
            (ColumnDictionary.is_pk.is_(True)) | (ColumnDictionary.is_unique.is_(True))
        ):
            key_flags.setdefault(row.dataset_id, {})[row.column_name] = {"pk": bool(row.is_pk), "unique": bool(row.is_unique)}
        options = []
        for dataset in datasets:
            database_name = getattr(dataset.database, "database_name", None)
            label = ".".join(part for part in (database_name, dataset.schema, dataset.table_name) if part)
            options.append(
                {
                    "id": dataset.id,
                    "dataset_name": dataset.table_name,
                    "label": label or dataset.table_name,
                    "database_name": database_name,
                    "schema": dataset.schema,
                    "columns": [str(column.column_name) for column in dataset.columns],
                    "column_types": {
                        str(column.column_name): str(getattr(column, "type", None) or "")[:64] for column in dataset.columns
                    },
                    "key_columns": key_flags.get(dataset.id, {}),
                }
            )
        return self.response(200, datasets=options)

    @expose("/dataset/<int:dataset_id>/dictionary", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_dataset_dictionary(self, dataset_id: int):
        """Return dictionary metadata in the same order as the dataset's Superset columns."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        dataset = db.session.get(SqlaTable, dataset_id)
        if dataset is None:
            return self.response(404, message="Dataset not found.")
        try:
            _seed_dictionary(dataset)
            dataset_repository = DatasetDictionaryRepository(db.session)
            rows = ColumnDictionaryRepository(db.session).list_for_dataset(dataset_id)
            return self.response(200, **_serialize_dictionary(dataset, dataset_repository.get(dataset_id), rows))
        except Exception:
            logger.exception("Could not load dataset dictionary (dataset_id=%s)", dataset_id)
            db.session.rollback()
            return self.response_500(message="Could not load dataset dictionary.")

    @expose("/dataset/<int:dataset_id>/dictionary/suggest", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def suggest_dataset_dictionary(self, dataset_id: int):
        """Stream and persist dataset-level and column-level dictionary suggestions."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")

        _ensure_dictionary_tables()
        dataset = db.session.get(SqlaTable, dataset_id)
        if dataset is None:
            return self.response(404, message="Dataset not found.")
        if not dataset.columns:
            return self.response_400(message="Dataset has no columns to describe.")
        try:
            get_chat_model()
        except RuntimeError as ex:
            # A missing API key would otherwise surface only as a generic error in the middle of the stream.
            logger.error("AI AutoFill unavailable: %s", ex)
            return self.response(503, message=str(ex))

        agent_context = {
            "dataset_name": dataset.table_name,
            "dataset_description": dataset.description,
            "columns": [
                {
                    "column_name": str(column.column_name),
                    "data_type": str(getattr(column, "type", None) or "UNKNOWN")[:128],
                    "superset_display_name": getattr(column, "verbose_name", None),
                    "description": getattr(column, "description", None),
                    "is_datetime": bool(getattr(column, "is_dttm", False)),
                }
                for column in dataset.columns
            ],
        }
        total = len(agent_context["columns"])
        table_name = dataset.table_name
        # The seed commits, so each LLM call below runs with no transaction open; a batch reads and writes its
        # rows only after the model has answered.
        _seed_dictionary(dataset)
        if not _claim_suggestion(dataset_id):
            return self.response(409, message="Dataset này đang được AI gợi ý, vui lòng đợi hoàn tất.")
        column_repository = ColumnDictionaryRepository(db.session)
        dataset_repository = DatasetDictionaryRepository(db.session)

        @stream_with_context
        def events():
            try:
                yield _sse_event("status", {"total": total, "processed": 0, "message": "Đang chuẩn bị gợi ý"})
                processed = 0
                for suggestions in suggest_column_dictionary_batches(agent_context):
                    rows_by_name = {row.column_name: row for row in column_repository.list_for_dataset(dataset_id)}
                    saved_suggestions = []
                    for item in suggestions:
                        row = rows_by_name.get(item["column_name"])
                        if row is None:
                            continue
                        values = {}
                        if not row.display_name.strip() or row.display_name.strip() == row.column_name:
                            values["display_name"] = str(item["display_name"] or row.column_name)[:255]
                        if not (row.unit or "").strip():
                            values["unit"] = str(item["unit"] or "")[:128] or None
                        if not (row.business_term or "").strip():
                            values["business_term"] = item["business_term"] or None
                        if values:
                            column_repository.update(row, values)
                        saved_suggestions.append(
                            {
                                "column_name": row.column_name,
                                "display_name": row.display_name,
                                "unit": row.unit,
                                "business_term": row.business_term,
                            }
                        )
                    db.session.commit()
                    processed += len(suggestions)
                    yield _sse_event(
                        "suggestions",
                        {
                            "suggestions": saved_suggestions,
                            "processed": processed,
                            "total": total,
                        },
                    )
                    yield _sse_event(
                        "status",
                        {"total": total, "processed": processed, "message": f"Đã xử lý {processed}/{total} cột"},
                    )
                dataset_suggestion = suggest_dataset_dictionary(agent_context)
                dataset_record = dataset_repository.get(dataset_id)
                dataset_values = {}
                if not (dataset_record.display_name or "").strip() or dataset_record.display_name.strip() == table_name:
                    dataset_values["display_name"] = dataset_suggestion["display_name"]
                if not (dataset_record.description or "").strip() and dataset_suggestion["description"]:
                    dataset_values["description"] = dataset_suggestion["description"]
                if not (dataset_record.grain or "").strip() and dataset_suggestion["grain"]:
                    dataset_values["grain"] = dataset_suggestion["grain"]
                if not dataset_record.create_column and dataset_suggestion["create_column"]:
                    dataset_values["create_column"] = dataset_suggestion["create_column"]
                if dataset_values:
                    dataset_repository.update(dataset_record, dataset_values)
                db.session.commit()
                yield _sse_event(
                    "dataset_suggestion",
                    {
                        "dataset": {
                            "display_name": dataset_record.display_name,
                            "description": dataset_record.description,
                            "grain": dataset_record.grain,
                            "create_column": dataset_record.create_column,
                        }
                    },
                )
                yield _sse_event("done", {"processed": processed, "total": total})
            except Exception as ex:
                db.session.rollback()
                logger.exception("Column dictionary agent failed (dataset_id=%s)", dataset_id)
                status_code = getattr(ex, "status_code", None)
                if status_code == 402:
                    message = "OpenRouter từ chối yêu cầu vì hết hạn mức credit của API key. Nạp thêm credit hoặc thử lại sau."
                elif status_code == 401:
                    message = "OpenRouter từ chối API key. Kiểm tra OPENROUTER_API_KEY trong extensions/ai-agents/.env."
                else:
                    message = "Không thể tạo gợi ý từ điển cột."
                # Batches saved before the failure are already committed and shown; only the rest is missing.
                yield _sse_event("error", {"message": message})
            finally:
                _release_suggestion(dataset_id)

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @expose("/dataset/<int:dataset_id>/dictionary", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def update_dataset_dictionary(self, dataset_id: int):
        """Bulk update editable dictionary metadata for columns in a Superset dataset."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        dataset = db.session.get(SqlaTable, dataset_id)
        if dataset is None:
            return self.response(404, message="Dataset not found.")
        actual_column_names = {str(column.column_name) for column in dataset.columns}
        try:
            payload = request.get_json(silent=True)
            updates = _validate_dictionary_payload(payload, actual_column_names, dataset_id)
        except (TypeError, ValueError) as ex:
            return self.response_400(message=str(ex))

        dataset_updates = payload.get("dataset", {})
        if not isinstance(dataset_updates, dict):
            return self.response_400(message="dataset must be an object.")
        unknown_fields = set(dataset_updates) - DATASET_DICTIONARY_FIELDS
        if unknown_fields:
            return self.response_400(message=f"dataset contains unsupported fields: {', '.join(sorted(unknown_fields))}.")
        for field in ("display_name", "description", "grain", "create_column"):
            if field not in dataset_updates:
                continue
            value = dataset_updates.get(field)
            if field == "display_name":
                if not isinstance(value, str) or not value.strip() or len(value) > 255:
                    return self.response_400(message="dataset.display_name must be a non-empty string of at most 255 characters.")
            elif value is not None and not isinstance(value, str):
                return self.response_400(message=f"dataset.{field} must be a string or null.")
        for field in ("description", "grain", "create_column"):
            value = dataset_updates.get(field)
            # A blank value means unset; a stored empty string would read back as a real value.
            if isinstance(value, str) and not value.strip():
                dataset_updates[field] = None
            elif field == "create_column" and isinstance(value, str):
                dataset_updates[field] = value.strip()
        if dataset_updates.get("dataset_type") not in (None, "base", "aggregate"):
            return self.response_400(message="dataset.dataset_type must be 'base', 'aggregate', or null.")
        if dataset_updates.get("create_column") and dataset_updates["create_column"] not in actual_column_names:
            return self.response_400(message="dataset.create_column must reference a column in this dataset.")
        layer_id = dataset_updates.get("layer_id")
        if layer_id is not None and (
            isinstance(layer_id, bool) or not isinstance(layer_id, int) or db.session.get(DataLayer, layer_id) is None
        ):
            return self.response_400(message="dataset.layer_id must reference an existing data layer or be null.")

        try:
            # Seed first: each seed commits, so it must not run between the updates below and their commit.
            _seed_dictionary(dataset)
            for referenced_id in {
                item["referenced_dataset_id"] for item in updates if item.get("referenced_dataset_id") is not None
            } - {dataset_id}:
                _seed_dictionary(db.session.get(SqlaTable, referenced_id))
            dataset_repository = DatasetDictionaryRepository(db.session)
            dataset_repository.update(dataset_repository.get(dataset_id), dataset_updates)
            column_repository = ColumnDictionaryRepository(db.session)
            rows_by_name = {row.column_name: row for row in column_repository.list_for_dataset(dataset_id)}
            for update in updates:
                column_name = update.pop("column_name")
                if "referenced_dataset_id" in update or "referenced_column_name" in update:
                    referenced_dataset_id = update.pop("referenced_dataset_id", None)
                    referenced_column_name = update.pop("referenced_column_name", None)
                    if referenced_dataset_id is None or referenced_column_name is None:
                        update["referenced_column"] = None
                    else:
                        referenced_row = column_repository.get_for_dataset_column(
                            referenced_dataset_id, referenced_column_name
                        )
                        if referenced_row is None:
                            raise ValueError("Referenced column no longer exists.")
                        update["referenced_column"] = referenced_row.id
                column_repository.update(rows_by_name[column_name], update)
            db.session.commit()
            rows = column_repository.list_for_dataset(dataset_id)
            return self.response(200, **_serialize_dictionary(dataset, dataset_repository.get(dataset_id), rows))
        except Exception:
            logger.exception("Could not save dataset dictionary (dataset_id=%s)", dataset_id)
            db.session.rollback()
            return self.response_500(message="Could not save dataset dictionary.")

    @expose("/business-model", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_business_model(self):
        """Return business domains, dictionary-derived lineage and metrics for one Superset database."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            return self.response_400(message="database_id is required.")
        _ensure_dictionary_tables()
        datasets = {
            dataset.id: dataset
            for dataset in db.session.query(SqlaTable).filter(SqlaTable.database_id == database_id).all()
        }
        try:
            domains = db.session.query(BusinessDomain).order_by(BusinessDomain.name).all()
            layers = db.session.query(DataLayer).order_by(DataLayer.level, DataLayer.sort_order, DataLayer.id).all()
            canvas = db.session.get(BusinessCanvas, database_id)
            lineage_canvas = db.session.get(LineageCanvas, database_id)
            return self.response(
                200,
                canvas=json.loads(canvas.layout) if canvas else None,
                lineage_canvas=json.loads(lineage_canvas.layout) if lineage_canvas else None,
                domains=[serialize_domain(domain, set(datasets)) for domain in domains],
                layers=[serialize_layer(layer) for layer in layers],
                classifications=dataset_classifications(db.session, list(datasets)),
                edges=lineage_edges(db.session, datasets),
                metrics=dataset_metrics(datasets),
            )
        except Exception:
            logger.exception("Could not load business model (database_id=%s)", database_id)
            db.session.rollback()
            return self.response_500(message="Could not load business model.")

    @staticmethod
    def _canvas_layout(payload: Any) -> dict[str, Any]:
        """Validate a business-view canvas: domain keys with their header and cells, and one cell per table."""

        def cell(value: Any) -> list[int]:
            if (
                not isinstance(value, list)
                or len(value) != 2
                or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
                or any(abs(item) > CANVAS_MAX_COORDINATE for item in value)
            ):
                raise ValueError("A cell must be a [col, row] pair of integers.")
            return [value[0], value[1]]

        if not isinstance(payload, dict):
            raise ValueError("Request body must be an object.")  # noqa: TRY004
        domains, tables = payload.get("domains"), payload.get("tables")
        if not isinstance(domains, list) or not isinstance(tables, dict):
            raise ValueError("domains must be a list and tables an object.")  # noqa: TRY004
        layout: dict[str, Any] = {"domains": [], "tables": {}}
        keys = set()
        for domain in domains:
            if not isinstance(domain, dict) or not CANVAS_DOMAIN_KEY.match(str(domain.get("key", ""))):
                raise ValueError("Each domain needs a key such as domain-1 or domain-unassigned.")
            if domain["key"] in keys:
                raise ValueError("Domain keys must be unique.")
            keys.add(domain["key"])
            cells = domain.get("cells")
            if not isinstance(cells, list) or not cells:
                raise ValueError("Each domain needs at least one cell.")
            layout["domains"].append(
                {"key": domain["key"], "header": cell(domain.get("header")), "cells": [cell(item) for item in cells]}
            )
        for dataset_id, position in tables.items():
            if not str(dataset_id).isdigit():
                raise ValueError("tables must be keyed by dataset ID.")
            layout["tables"][str(int(dataset_id))] = cell(position)
        if sum(len(domain["cells"]) for domain in layout["domains"]) + len(layout["tables"]) > CANVAS_MAX_CELLS:
            raise ValueError("The canvas has too many cells.")
        return layout

    @expose("/business-canvas", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def save_business_canvas(self):
        """Store where the business view draws each domain and table for one Superset database."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            return self.response_400(message="database_id is required.")
        _ensure_dictionary_tables()
        if db.session.get(Database, database_id) is None:
            return self.response(404, message="Database not found.")
        try:
            layout = self._canvas_layout(request.get_json(silent=True))
        except ValueError as ex:
            return self.response_400(message=str(ex))
        try:
            canvas = db.session.get(BusinessCanvas, database_id)
            if canvas is None:
                canvas = BusinessCanvas(database_id=database_id)
                db.session.add(canvas)
            canvas.layout = json.dumps(layout, separators=(",", ":"))
            db.session.commit()
            return self.response(200, database_id=database_id)
        except Exception:
            logger.exception("Could not save business canvas (database_id=%s)", database_id)
            db.session.rollback()
            return self.response_500(message="Could not save business canvas.")

    @staticmethod
    def _lineage_layout(payload: Any) -> dict[str, Any]:
        """Validate a lineage canvas: card positions and edge shapes keyed by their canvas IDs."""

        def number(value: Any) -> float:
            if isinstance(value, bool) or not isinstance(value, int | float) or abs(value) > CANVAS_MAX_COORDINATE:
                raise ValueError("Coordinates must be numbers within the canvas.")
            return round(float(value), 1)

        def point(value: Any) -> list[float]:
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError("A point must be an [x, y] pair.")
            return [number(value[0]), number(value[1])]

        def numbers(value: Any) -> list[float]:
            if not isinstance(value, list) or len(value) > LINEAGE_MAX_POINTS:
                raise ValueError(f"An edge holds at most {LINEAGE_MAX_POINTS} points.")
            return [number(item) for item in value]

        if not isinstance(payload, dict):
            raise ValueError("Request body must be an object.")  # noqa: TRY004
        nodes, edges = payload.get("nodes", {}), payload.get("edges", {})
        if not isinstance(nodes, dict) or not isinstance(edges, dict):
            raise ValueError("nodes and edges must be objects.")  # noqa: TRY004
        if len(nodes) + len(edges) > LINEAGE_MAX_ITEMS:
            raise ValueError("The lineage canvas has too many items.")
        layout: dict[str, Any] = {"nodes": {}, "edges": {}}
        for key, position in nodes.items():
            if not LINEAGE_NODE_KEY.match(str(key)):
                raise ValueError("nodes must be keyed by card IDs such as table-1 or metric-1.")
            layout["nodes"][key] = point(position)
        for key, shape in edges.items():
            if not LINEAGE_EDGE_KEY.match(str(key)) or not isinstance(shape, dict):
                raise ValueError("edges must be keyed by edge IDs such as flow-1-2 or metric-edge-1.")
            if shape.get("style") not in LINEAGE_EDGE_STYLES:
                raise ValueError("An edge style must be orthogonal, straight or curved.")
            waypoints = shape.get("waypoints", [])
            if not isinstance(waypoints, list) or len(waypoints) > LINEAGE_MAX_POINTS:
                raise ValueError(f"An edge holds at most {LINEAGE_MAX_POINTS} points.")
            label, ports = shape.get("label"), shape.get("ports", [0, 0])
            layout["edges"][key] = {
                "style": shape["style"],
                "coords": numbers(shape.get("coords", [])),
                "waypoints": [point(item) for item in waypoints],
                "label": None if label is None else point(label),
                "ports": point(ports),
            }
        return layout

    @expose("/lineage-canvas", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def save_lineage_canvas(self):
        """Store the lineage cards the user moved and the edges the user shaped for one Superset database."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            return self.response_400(message="database_id is required.")
        _ensure_dictionary_tables()
        if db.session.get(Database, database_id) is None:
            return self.response(404, message="Database not found.")
        try:
            layout = self._lineage_layout(request.get_json(silent=True))
        except ValueError as ex:
            return self.response_400(message=str(ex))
        try:
            canvas = db.session.get(LineageCanvas, database_id)
            if canvas is None:
                canvas = LineageCanvas(database_id=database_id)
                db.session.add(canvas)
            canvas.layout = json.dumps(layout, separators=(",", ":"))
            db.session.commit()
            return self.response(200, database_id=database_id)
        except Exception:
            logger.exception("Could not save lineage canvas (database_id=%s)", database_id)
            db.session.rollback()
            return self.response_500(message="Could not save lineage canvas.")

    @expose("/data-layers", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_data_layers(self):
        """List admin-defined data layers in flow order."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        layers = db.session.query(DataLayer).order_by(DataLayer.level, DataLayer.sort_order, DataLayer.id).all()
        return self.response(200, layers=[serialize_layer(layer) for layer in layers])

    @staticmethod
    def _layer_values(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Request body must be an object.")  # noqa: TRY004
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
            raise ValueError("name must be a non-empty string of at most 255 characters.")
        description = payload.get("description")
        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string or null.")
        color = payload.get("color")
        if color is not None and (not isinstance(color, str) or len(color) > 16):
            raise ValueError("color must be a string of at most 16 characters or null.")
        return {"name": name.strip(), "description": (description or "").strip() or None, "color": color or None}

    def _save_layer(self, layer: DataLayer | None):
        try:
            values = self._layer_values(request.get_json(silent=True))
        except ValueError as ex:
            return self.response_400(message=str(ex))
        duplicate = db.session.query(DataLayer).filter(DataLayer.name == values["name"]).first()
        if duplicate is not None and (layer is None or duplicate.id != layer.id):
            return self.response_400(message="Tên tầng dữ liệu đã tồn tại.")
        if layer is None:
            # A new layer starts a level of its own after the existing ones; the levels order then places it.
            last = db.session.query(DataLayer).order_by(DataLayer.sort_order.desc()).first()
            top = db.session.query(DataLayer).order_by(DataLayer.level.desc()).first()
            layer = DataLayer(sort_order=(last.sort_order + 1) if last else 0, level=(top.level + 1) if top else 0)
            db.session.add(layer)
        for attribute, value in values.items():
            setattr(layer, attribute, value)
        db.session.commit()
        return self.response(200, layer=serialize_layer(layer))

    @expose("/data-layers", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def create_data_layer(self):
        """Append a data layer after the existing ones."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        return self._save_layer(None)

    @expose("/data-layers/<int:layer_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def update_data_layer(self, layer_id: int):
        """Rename or recolour a data layer."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        layer = db.session.get(DataLayer, layer_id)
        if layer is None:
            return self.response(404, message="Data layer not found.")
        return self._save_layer(layer)

    @expose("/data-layers/<int:layer_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def delete_data_layer(self, layer_id: int):
        """Delete a data layer; its datasets become unclassified."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        layer = db.session.get(DataLayer, layer_id)
        if layer is None:
            return self.response(404, message="Data layer not found.")
        db.session.query(DatasetDictionary).filter(DatasetDictionary.layer_id == layer_id).update(
            {DatasetDictionary.layer_id: None}, synchronize_session=False
        )
        db.session.delete(layer)
        db.session.commit()
        return self.response(200, id=layer_id)

    @expose("/data-layers/order", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def reorder_data_layers(self):
        """Set the levels of all data layers, in flow order, from a list of levels that each list their layer IDs."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        levels = payload.get("levels") if isinstance(payload, dict) else None
        layers = {layer.id: layer for layer in db.session.query(DataLayer).all()}
        if not isinstance(levels, list) or not all(isinstance(level, list) and level for level in levels):
            return self.response_400(message="levels must be a list of non-empty lists of data layer IDs.")
        ids = [layer_id for level in levels for layer_id in level]
        if any(isinstance(layer_id, bool) or not isinstance(layer_id, int) for layer_id in ids) or sorted(ids) != sorted(layers):
            return self.response_400(message="levels must list every data layer exactly once.")
        for level_index, level in enumerate(levels):
            for layer_id in level:
                layers[layer_id].level = level_index
        for position, layer_id in enumerate(ids):
            layers[layer_id].sort_order = position
        db.session.commit()
        return self.response(200, layers=[serialize_layer(layers[layer_id]) for layer_id in ids])

    @staticmethod
    def _domain_values(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Request body must be an object.")  # noqa: TRY004
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
            raise ValueError("name must be a non-empty string of at most 255 characters.")
        description = payload.get("description")
        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string or null.")
        color = payload.get("color")
        if color is not None and (not isinstance(color, str) or len(color) > 16):
            raise ValueError("color must be a string of at most 16 characters or null.")
        dataset_ids = payload.get("dataset_ids", [])
        if not isinstance(dataset_ids, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in dataset_ids):
            raise ValueError("dataset_ids must be a list of dataset IDs.")
        datasets = db.session.query(SqlaTable).filter(SqlaTable.id.in_(dataset_ids)).all() if dataset_ids else []
        if len(datasets) != len(set(dataset_ids)):
            raise ValueError("dataset_ids contains unknown datasets.")
        ensure_dataset_dictionaries(db.session, datasets)
        dictionaries = db.session.query(DatasetDictionary).filter(DatasetDictionary.id.in_(dataset_ids)).all()
        return {
            "name": name.strip(),
            "description": (description or "").strip() or None,
            "color": color or None,
            "datasets": dictionaries,
        }

    def _save_domain(self, domain: BusinessDomain | None):
        _ensure_dictionary_tables()
        try:
            values = self._domain_values(request.get_json(silent=True))
        except ValueError as ex:
            db.session.rollback()
            return self.response_400(message=str(ex))
        duplicate = db.session.query(BusinessDomain).filter(BusinessDomain.name == values["name"]).first()
        if duplicate is not None and (domain is None or duplicate.id != domain.id):
            db.session.rollback()
            return self.response_400(message="Tên nghiệp vụ đã tồn tại.")
        try:
            if domain is None:
                domain = BusinessDomain()
                db.session.add(domain)
            for attribute, value in values.items():
                setattr(domain, attribute, value)
            db.session.commit()
            return self.response(200, domain=serialize_domain(domain))
        except Exception:
            logger.exception("Could not save business domain")
            db.session.rollback()
            return self.response_500(message="Could not save business domain.")

    @expose("/business-domains", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def create_business_domain(self):
        """Create a business domain and assign datasets to it."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        return self._save_domain(None)

    @expose("/business-domains/<int:domain_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def update_business_domain(self, domain_id: int):
        """Rename a business domain or replace its datasets."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        domain = db.session.get(BusinessDomain, domain_id)
        if domain is None:
            return self.response(404, message="Business domain not found.")
        return self._save_domain(domain)

    @expose("/business-domains/<int:domain_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def delete_business_domain(self, domain_id: int):
        """Delete a business domain; its datasets are kept."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        domain = db.session.get(BusinessDomain, domain_id)
        if domain is None:
            return self.response(404, message="Business domain not found.")
        db.session.delete(domain)
        db.session.commit()
        return self.response(200, id=domain_id)

    @staticmethod
    def _edge_key(payload: Any) -> tuple[int, int, str]:
        if not isinstance(payload, dict):
            raise ValueError("Request body must be an object.")  # noqa: TRY004
        source_id, target_id, kind = payload.get("source"), payload.get("target"), payload.get("kind")
        for value in (source_id, target_id):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("source and target must be dataset IDs.")  # noqa: TRY004
        if source_id == target_id:
            raise ValueError("An edge cannot connect a dataset to itself.")
        if kind not in EDGE_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(EDGE_KINDS)}.")
        datasets = db.session.query(SqlaTable).filter(SqlaTable.id.in_([source_id, target_id])).all()
        if len(datasets) != 2:
            raise ValueError("Unknown source or target dataset.")
        ensure_dataset_dictionaries(db.session, datasets)
        return source_id, target_id, kind

    @staticmethod
    def _edge_override(key: tuple[int, int, str]) -> tuple[LineageEdge | None, bool]:
        """The override row for an edge and whether the data dictionary infers that edge."""
        datasets = {
            dataset.id: dataset for dataset in db.session.query(SqlaTable).filter(SqlaTable.id.in_(key[:2])).all()
        }
        inferred = infer_dictionary_edges(db.session, datasets)
        return find_edge_override(db.session, key, inferred), key in inferred
    @expose("/lineage-edges", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def add_lineage_edge(self):
        """Add a manual lineage edge, or restore an inferred edge that was hidden."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        try:
            source_id, target_id, kind = self._edge_key(request.get_json(silent=True))
        except ValueError as ex:
            db.session.rollback()
            return self.response_400(message=str(ex))
        edge, _ = self._edge_override((source_id, target_id, kind))

        if edge is None:
            db.session.add(LineageEdge(source_dataset_id=source_id, target_dataset_id=target_id, kind=kind))
        elif edge.is_hidden:
            # Unhiding an inferred edge only needs the override removed.
            db.session.delete(edge)
        else:
            # A colour-only row for an inferred edge becomes a manual edge that outlives the FK declaration.
            edge.is_manual = True
        db.session.commit()
        return self.response(200, source=source_id, target=target_id, kind=kind)

    @expose("/lineage-edges/color", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def set_lineage_edge_color(self):
        """Set or clear the display colour of a lineage edge, whether manual or inferred from the dictionary."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        try:
            source_id, target_id, kind = self._edge_key(payload)
        except ValueError as ex:
            db.session.rollback()
            return self.response_400(message=str(ex))
        color = payload.get("color")
        if color is not None and (not isinstance(color, str) or not color.startswith("#") or len(color) > 16):
            db.session.rollback()
            return self.response_400(message="color must be a hex colour such as #2563eb, or null.")
        edge, _ = self._edge_override((source_id, target_id, kind))

        if edge is None:
            if color is not None:
                db.session.add(
                    LineageEdge(
                        source_dataset_id=source_id, target_dataset_id=target_id, kind=kind, is_manual=False, color=color
                    )
                )
        elif color is None and not edge.is_manual and not edge.is_hidden:
            db.session.delete(edge)
        else:
            edge.color = color
        db.session.commit()
        return self.response(200, source=source_id, target=target_id, kind=kind, color=color)

    @expose("/lineage-edges", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def remove_lineage_edge(self):
        """Remove a manual lineage edge, or hide an edge inferred from the data dictionary."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        try:
            source_id, target_id, kind = self._edge_key(request.get_json(silent=True))
        except ValueError as ex:
            db.session.rollback()
            return self.response_400(message=str(ex))
        edge, inferred = self._edge_override((source_id, target_id, kind))

        if inferred:

            # The dictionary keeps producing this edge, so it is suppressed with a hidden override.
            if edge is None:
                db.session.add(
                    LineageEdge(source_dataset_id=source_id, target_dataset_id=target_id, kind=kind, is_hidden=True)
                )
            else:
                edge.is_hidden = True
        elif edge is not None:
            db.session.delete(edge)
        db.session.commit()
        return self.response(200, source=source_id, target=target_id, kind=kind)

    @staticmethod
    def _glossary_revision(revision: GlossaryTermRevision, links: list[GlossaryTermLink]) -> dict[str, Any]:
        return {
            "id": revision.id,
            "term_id": revision.term_id,
            "revision_number": revision.revision_number,
            "canonical_name": revision.term.canonical_name,
            "definition": revision.definition,
            "synonyms": revision.synonyms or [],
            "provenance": revision.provenance,
            "status": revision.status,
            "is_current": revision.is_current,
            "created_at": revision.created_on.isoformat() if revision.created_on else None,
            "approved_at": revision.approved_at.isoformat() if revision.approved_at else None,
            "revoked_at": revision.revoked_at.isoformat() if revision.revoked_at else None,
            "links": [
                {"kind": link.kind, "dataset_id": link.dataset_id, "column_name": link.column_name, "metric_id": link.metric_id}
                for link in links
            ],
        }

    def _glossary_term(self, term: GlossaryTerm, revisions: list[GlossaryTermRevision]) -> dict[str, Any]:
        serialized = [self._glossary_revision(revision, self._glossary_links(revision.id)) for revision in revisions]
        current = next((revision for revision in serialized if revision["is_current"]), None)
        return {
            "id": term.id,
            "canonical_name": term.canonical_name,
            "owner_id": term.owner_id,
            "steward_id": term.steward_id,
            "current_revision": current,
            "revisions": serialized,
        }

    def _glossary_term_by_id(self, term_id: int) -> GlossaryTerm | None:
        return db.session.get(GlossaryTerm, term_id)

    @staticmethod
    def _glossary_links(revision_id: int) -> list[GlossaryTermLink]:
        return db.session.query(GlossaryTermLink).filter(GlossaryTermLink.revision_id == revision_id).all()

    @staticmethod
    def _glossary_user_exists(user_id: int) -> bool:
        return security_manager.get_user_by_id(user_id) is not None

    @staticmethod
    def _glossary_link_target(link: GlossaryTermLink, dataset: SqlaTable) -> Any | None:
        if link.kind == "dataset":
            return None
        if link.kind == "column":
            return next((column for column in dataset.columns if column.column_name == link.column_name), None)
        return next((metric for metric in dataset.metrics if metric.id == link.metric_id), None)

    def _glossary_live_fingerprint(self, link: GlossaryTermLink) -> str | None:
        dataset = db.session.get(SqlaTable, link.dataset_id)
        if dataset is None:
            return None
        target = self._glossary_link_target(link, dataset)
        if link.kind != "dataset" and target is None:
            return None
        return glossary_link_fingerprint(dataset, link.kind, target)

    @expose("/glossary", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def list_glossary(self):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        terms = db.session.query(GlossaryTerm).order_by(GlossaryTerm.canonical_name).all()
        return self.response(
            200,
            terms=[
                self._glossary_term(
                    term,
                    db.session.query(GlossaryTermRevision)
                    .filter_by(term_id=term.id, is_current=True)
                    .order_by(GlossaryTermRevision.revision_number)
                    .all(),
                )
                for term in terms
            ],
        )

    @expose("/glossary/<int:term_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_glossary(self, term_id: int):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        term = self._glossary_term_by_id(term_id)
        if term is None:
            return self.response(404, message="Glossary term not found.")
        revisions = (
            db.session.query(GlossaryTermRevision)
            .filter_by(term_id=term_id)
            .order_by(GlossaryTermRevision.revision_number)
            .all()
        )
        return self.response(200, term=self._glossary_term(term, revisions))

    @expose("/glossary", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def create_glossary(self):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        try:
            revision = create_draft(db.session, request.get_json(silent=True), current_user.id, lambda key: db.session.get(SqlaTable, key), self._glossary_user_exists)
            db.session.commit()
        except GlossaryConflictError as ex:
            db.session.rollback()
            return self.response(409, message=str(ex))
        except GlossaryValidationError as ex:
            db.session.rollback()
            return self.response_400(message=str(ex))
        return self.response(201, term=self._glossary_term(revision.term, [revision]))

    @expose("/glossary/<int:term_id>/draft", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def update_glossary_draft(self, term_id: int):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        current = db.session.query(GlossaryTermRevision).filter_by(term_id=term_id, is_current=True).one_or_none()
        if current is None:
            return self.response(404, message="Glossary term not found.")
        try:
            expected_revision = payload.get("expected_revision") if isinstance(payload, dict) else None
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
                raise GlossaryValidationError("expected_revision is required.")
            content = dict(payload)
            content.pop("expected_revision")
            revision = update_draft(db.session, current, content, expected_revision, current_user.id, lambda key: db.session.get(SqlaTable, key), self._glossary_user_exists)
            db.session.commit()
        except GlossaryConflictError as ex:
            db.session.rollback()
            return self.response(409, message=str(ex))
        except GlossaryValidationError as ex:
            db.session.rollback()
            return self.response_400(message=str(ex))
        return self.response(200, term=self._glossary_term(revision.term, [revision]))

    def _glossary_lifecycle(
        self, term_id: int, event: str, expected_revision: int, actor_id: int, reason: str | None
    ):
        _ensure_dictionary_tables()
        revision = db.session.query(GlossaryTermRevision).filter_by(term_id=term_id, is_current=True).one_or_none()
        if revision is None:
            return self.response(404, message="Glossary term not found.")
        try:
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
                raise GlossaryValidationError("expected_revision is required.")
            if event == "approve":
                approve_revision(db.session, revision, expected_revision, actor_id, reason)
            else:
                revoke_revision(db.session, revision, expected_revision, actor_id, reason)
            db.session.commit()
        except GlossaryConflictError as ex:
            db.session.rollback()
            return self.response(409, message=str(ex))
        except GlossaryValidationError as ex:
            db.session.rollback()
            return self.response_400(message=str(ex))
        return self.response(200, term=self._glossary_term(revision.term, [revision]))

    @expose("/glossary/<int:term_id>/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def approve_glossary(self, term_id: int):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        payload = request.get_json(silent=True)
        expected_revision = payload.get("expected_revision") if isinstance(payload, dict) else None
        reason = payload.get("reason") if isinstance(payload, dict) else None
        return self._glossary_lifecycle(term_id, "approve", expected_revision, current_user.id, reason)

    @expose("/glossary/<int:term_id>/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def revoke_glossary(self, term_id: int):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        payload = request.get_json(silent=True)
        expected_revision = payload.get("expected_revision") if isinstance(payload, dict) else None
        reason = payload.get("reason") if isinstance(payload, dict) else None
        return self._glossary_lifecycle(term_id, "revoke", expected_revision, current_user.id, reason)

    @expose("/glossary/<int:term_id>/audit", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def glossary_audit(self, term_id: int):
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        _ensure_dictionary_tables()
        events = db.session.query(GlossaryTermAuditEvent).filter_by(term_id=term_id).order_by(GlossaryTermAuditEvent.id).all()
        return self.response(
            200,
            events=[
                {
                    "id": row.id,
                    "action": row.event_type,
                    "revision_number": row.revision_number,
                    "actor_id": row.actor_id,
                    "reason": row.reason,
                    "created_at": row.occurred_at.isoformat(),
                }
                for row in events
            ],
        )

    @expose("/glossary/discovery", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def glossary_discovery(self):
        """Return only approved, current, fresh links to caller-authorized datasets."""
        _ensure_dictionary_tables()
        rows = db.session.query(GlossaryTermRevision).filter_by(status="approved", is_current=True).all()
        terms = []
        for revision in rows:
            visible_links = []
            for link in self._glossary_links(revision.id):
                dataset = db.session.get(SqlaTable, link.dataset_id)
                if dataset is None or not self._can_access_semantic_query_dataset(dataset):
                    continue
                target = self._glossary_link_target(link, dataset)
                if link.kind != "dataset" and target is None:
                    continue
                if glossary_link_fingerprint(dataset, link.kind, target) != link.fingerprint:
                    continue
                visible_links.append(
                    {"kind": link.kind, "dataset_id": link.dataset_id, "column_name": link.column_name, "metric_id": link.metric_id}
                )
            if not visible_links:
                continue
            terms.append(
                {
                    "term_id": revision.term_id,
                    "canonical_name": revision.term.canonical_name,
                    "definition": revision.definition,
                    "synonyms": revision.synonyms or [],
                    "links": visible_links,
                }
            )
        return self.response(200, terms=terms)
