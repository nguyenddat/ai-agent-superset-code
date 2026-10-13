import json
import logging
from typing import Any

from flask import Response, request, stream_with_context
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from sqlalchemy import inspect, text
from superset import db
from superset.connectors.sqla.models import SqlaTable
from superset.models.dashboard import Dashboard
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ...agent_package.column_dictionary import suggest_column_dictionary_batches, suggest_dataset_dictionary
from ...models.column_dictionary import ColumnDictionary
from ...models.dataset_dictionary import DatasetDictionary
from ..data_dictionary.repository.repo_column_dictionary import ColumnDictionaryRepository
from ..data_dictionary.repository.repo_dataset_dictionary import DatasetDictionaryRepository


SEMANTIC_LAYER_DATASET_IDS_KEY = "text_to_bi_semantic_layer_dataset_ids"
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
DATASET_DICTIONARY_FIELDS = {"display_name", "description", "grain", "create_column", "dataset_type"}


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
                values[field] = value
        normalized.append(values)
    return normalized


def _serialize_dictionary(
    dataset: SqlaTable,
    dictionary: DatasetDictionary,
    columns: list[Any],
) -> dict[str, Any]:
    records = {column.column_name: column for column in columns}
    references_by_id = {
        row.referenced_column: db.session.get(ColumnDictionary, row.referenced_column)
        for row in columns
        if row.referenced_column is not None
    }
    referenced_dataset_ids = {row.dataset_id for row in references_by_id.values() if row is not None}
    datasets_by_id = {
        referenced_id: db.session.get(SqlaTable, referenced_id)
        for referenced_id in referenced_dataset_ids
    }

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
    for actual_column in dataset.columns:
        column_name = str(actual_column.column_name)
        if column_name not in existing:
            values = _column_metadata_values(actual_column)
            existing[column_name] = repository.add(ColumnDictionary(dataset_id=dataset.id, **values))
    return list(existing.values())


def _ensure_dictionary_tables():
    """Create extension tables and upgrade the earlier column dictionary schema."""
    inspector = inspect(db.engine)
    if inspector.has_table(ColumnDictionary.__tablename__):
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

    DatasetDictionary.__table__.create(bind=db.engine, checkfirst=True)
    ColumnDictionary.__table__.create(bind=db.engine, checkfirst=True)

    with db.engine.begin() as connection:
        dataset_columns = {
            column["name"] for column in inspect(connection).get_columns(DatasetDictionary.__tablename__)
        }
        dataset_columns_to_add = (
            ("description", "TEXT"),
            ("grain", "TEXT"),
            ("create_column", "VARCHAR(255)"),
            ("dataset_type", "VARCHAR(32)"),
        )
        for column_name, column_type in dataset_columns_to_add:
            if column_name not in dataset_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE text_to_bi_dataset_dictionary ADD COLUMN {column_name} {column_type}"
                    )
                )

    with db.engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns(ColumnDictionary.__tablename__)}
        if "column_name" not in columns:
            connection.execute(
                text("ALTER TABLE text_to_bi_column_dictionary ADD COLUMN column_name VARCHAR(255)")
            )
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
                "FROM tables "
                "ON CONFLICT (id) DO NOTHING"
            )
        )

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
    description="Admin access check for the Semantic Layer dashboard extension.",
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

    @expose("/datasets/reference-options", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_reference_options(self):
        """List Superset datasets and columns for foreign key references."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        datasets = db.session.query(SqlaTable).order_by(SqlaTable.table_name, SqlaTable.id).all()
        options = []
        for dataset in datasets:
            database_name = getattr(dataset.database, "database_name", None)
            label = ".".join(part for part in (database_name, dataset.schema, dataset.table_name) if part)
            options.append(
                {
                    "id": dataset.id,
                    "dataset_name": dataset.table_name,
                    "label": label or dataset.table_name,
                    "columns": [str(column.column_name) for column in dataset.columns],
                }
            )
        return self.response(200, datasets=options)

    @expose("/dashboard/<int:dashboard_id>/datasets", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_dashboard_datasets(self, dashboard_id: int):
        """Return datasets explicitly attached to a dashboard's semantic layer."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        dashboard = db.session.get(Dashboard, dashboard_id)
        if dashboard is None:
            return self.response(404, message="Dashboard not found.")
        try:
            metadata = json.loads(dashboard.json_metadata or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        dataset_ids = metadata.get(SEMANTIC_LAYER_DATASET_IDS_KEY, [])
        dataset_ids = sorted({int(value) for value in dataset_ids if str(value).isdigit()})
        return self.response(200, dataset_ids=dataset_ids)

    @expose("/dashboard/<int:dashboard_id>/datasets", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    def add_dashboard_dataset(self, dashboard_id: int):
        """Attach an existing dataset to a dashboard's semantic layer."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        dashboard = db.session.get(Dashboard, dashboard_id)
        if dashboard is None:
            return self.response(404, message="Dashboard not found.")
        payload = request.get_json(silent=True) or {}
        try:
            dataset_id = int(payload.get("dataset_id"))
        except (TypeError, ValueError):
            return self.response_400(message="dataset_id must be an integer.")
        if dataset_id <= 0:
            return self.response_400(message="dataset_id must be a positive integer.")
        if db.session.get(SqlaTable, dataset_id) is None:
            return self.response(404, message="Dataset not found.")
        try:
            metadata = json.loads(dashboard.json_metadata or "{}")
            dataset_ids = metadata.get(SEMANTIC_LAYER_DATASET_IDS_KEY, [])
            existing_ids = {int(value) for value in dataset_ids if str(value).isdigit()}
            existing_ids.add(dataset_id)
            metadata[SEMANTIC_LAYER_DATASET_IDS_KEY] = sorted(existing_ids)
            dashboard.json_metadata = json.dumps(metadata)
            db.session.commit()
            return self.response(200, dataset_ids=metadata[SEMANTIC_LAYER_DATASET_IDS_KEY])
        except Exception as ex:  # noqa: BLE001
            db.session.rollback()
            return self.response_500(message=str(ex))

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
            dataset_repository = DatasetDictionaryRepository(db.session)
            if dataset_repository.get(dataset_id) is None:
                dataset_repository.add(
                    DatasetDictionary(
                        id=dataset_id,
                        dataset_name=dataset.table_name,
                        display_name=dataset.table_name,
                        description=dataset.description,
                    )
                )
            column_repository = ColumnDictionaryRepository(db.session)
            _seed_dictionary_columns(dataset, column_repository)
            db.session.commit()
            rows = column_repository.list_for_dataset(dataset_id)
            return self.response(200, **_serialize_dictionary(dataset, dataset_repository.get(dataset_id), rows))
        except Exception:  # noqa: BLE001
            db.session.rollback()
            return self.response_500(message="Could not load dataset dictionary.")

    @expose("/dataset/<int:dataset_id>/dictionary/suggest", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    def suggest_dataset_dictionary(self, dataset_id: int):
        """Stream and persist dataset-level and column-level dictionary suggestions."""
        from flask_wtf.csrf import validate_csrf
        from wtforms import ValidationError

        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return self.response(403, message="CSRF token không hợp lệ.")

        _ensure_dictionary_tables()
        dataset = db.session.get(SqlaTable, dataset_id)
        if dataset is None:
            return self.response(404, message="Dataset not found.")
        if not dataset.columns:
            return self.response_400(message="Dataset has no columns to describe.")

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
        column_repository = ColumnDictionaryRepository(db.session)
        dictionary_rows = _seed_dictionary_columns(dataset, column_repository)
        rows_by_name = {row.column_name: row for row in dictionary_rows}
        dataset_repository = DatasetDictionaryRepository(db.session)
        dataset_record = dataset_repository.get(dataset_id)
        if dataset_record is None:
            dataset_record = dataset_repository.add(
                DatasetDictionary(
                    id=dataset_id,
                    dataset_name=dataset.table_name,
                    display_name=dataset.table_name,
                    description=dataset.description,
                )
            )

        @stream_with_context
        def events():
            yield _sse_event("status", {"total": total, "processed": 0, "message": "Đang chuẩn bị gợi ý"})
            try:
                processed = 0
                for suggestions in suggest_column_dictionary_batches(agent_context):
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
                dataset_values = {}
                if (
                    not (dataset_record.display_name or "").strip()
                    or dataset_record.display_name.strip() == dataset.table_name
                ):
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
            except Exception:  # noqa: BLE001
                db.session.rollback()
                logger.exception("Column dictionary agent failed (dataset_id=%s)", dataset_id)
                yield _sse_event("error", {"message": "Không thể tạo gợi ý từ điển cột."})

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @expose("/dataset/<int:dataset_id>/dictionary", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
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
        if dataset_updates.get("dataset_type") not in (None, "base", "aggregate"):
            return self.response_400(message="dataset.dataset_type must be 'base', 'aggregate', or null.")
        if dataset_updates.get("create_column") and dataset_updates["create_column"] not in actual_column_names:
            return self.response_400(message="dataset.create_column must reference a column in this dataset.")

        try:
            dataset_repository = DatasetDictionaryRepository(db.session)
            if dataset_repository.get(dataset_id) is None:
                dataset_repository.add(
                    DatasetDictionary(
                        id=dataset_id,
                        dataset_name=dataset.table_name,
                        display_name=dataset.table_name,
                        description=dataset.description,
                    )
                )
            dataset_record = dataset_repository.get(dataset_id)
            dataset_repository.update(dataset_record, dataset_updates)
            column_repository = ColumnDictionaryRepository(db.session)
            rows = _seed_dictionary_columns(dataset, column_repository)
            rows_by_name = {row.column_name: row for row in rows}
            for update in updates:
                column_name = update.pop("column_name")
                if "referenced_dataset_id" in update or "referenced_column_name" in update:
                    referenced_dataset_id = update.pop("referenced_dataset_id", None)
                    referenced_column_name = update.pop("referenced_column_name", None)
                    if referenced_dataset_id is None or referenced_column_name is None:
                        update["referenced_column"] = None
                    else:
                        referenced_dataset = db.session.get(SqlaTable, referenced_dataset_id)
                        dataset_repository = DatasetDictionaryRepository(db.session)
                        if dataset_repository.get(referenced_dataset_id) is None:
                            dataset_repository.add(
                                DatasetDictionary(
                                    id=referenced_dataset_id,
                                    dataset_name=referenced_dataset.table_name,
                                    display_name=referenced_dataset.table_name,
                                    description=referenced_dataset.description,
                                )
                            )
                        referenced_rows = _seed_dictionary_columns(referenced_dataset, column_repository)
                        referenced_row = next(
                            (row for row in referenced_rows if row.column_name == referenced_column_name),
                            None,
                        )
                        if referenced_row is None:
                            raise ValueError("Referenced column no longer exists.")
                        update["referenced_column"] = referenced_row.id
                column_repository.update(rows_by_name[column_name], update)
            db.session.commit()
            rows = column_repository.list_for_dataset(dataset_id)
            return self.response(200, **_serialize_dictionary(dataset, dataset_repository.get(dataset_id), rows))
        except Exception:  # noqa: BLE001
            db.session.rollback()
            return self.response_500(message="Could not save dataset dictionary.")
