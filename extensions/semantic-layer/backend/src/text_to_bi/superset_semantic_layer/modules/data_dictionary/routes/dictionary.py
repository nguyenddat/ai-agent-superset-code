import json
import logging
from typing import Any

from flask import Response, request, stream_with_context
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset import db
from superset.connectors.sqla.models import SqlaTable

from ....agent_package.chat_models import get_chat_model
from ....agent_package.column_dictionary import suggest_column_dictionary_batches, suggest_dataset_dictionary
from ....common.exceptions import SemanticLayerError
from ....common.utils.type_formatter import sse_event
from ....core.database import (
    datasets_by_name,
    ensure_dictionary_tables,
    get_dataset,
    handle_errors,
    is_internal_dataset,
    require_dataset,
    rollback_on_error,
    seed_dictionary,
)
from ....core.exceptions import DatasetAccessError
from ....core.security import csrf_protected, is_superset_access_error, require_admin
from ...business_model.dependencies import data_layer_repository
from ..dependencies import column_dictionary_repository, dataset_dictionary_repository, dataset_grain_repository
from ..exceptions import (
    AutoFillUnavailableError,
    DataDictionaryValidationError,
    NoColumnsToDescribeError,
    NotIndicatorCatalogError,
    ReferencedColumnMissingError,
    SuggestionInProgressError,
)
from ..models import ColumnDictionary, DatasetDictionary
from ..services.dictionary import (
    DATASET_DICTIONARY_FIELDS,
    DATASET_TIME_FIELDS,
    claim_suggestion,
    release_suggestion,
    serialize_dictionary,
    validate_dictionary_payload,
)
from ..services.indicators import (
    build_indicators_payload,
    checked_indicator_model,
    indicators_from_rows,
    stored_indicator_model,
)
from ..services.time_semantics import (
    build_grain_profile_payload,
    checked_time_semantics,
    default_temporal_kind,
    grain_profile_from_rows,
)

logger = logging.getLogger(__name__)


class DataDictionaryRoutes:
    """SemanticLayerAPI routes for the Data Dictionary: metadata, AI AutoFill, grain and indicators."""

    @expose("/datasets/reference-options", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_reference_options(self):
        """List Superset datasets and columns for foreign key references."""
        require_admin()
        ensure_dictionary_tables()
        datasets = datasets_by_name()
        # Key flags declared in the data dictionary let the picker offer key columns as FK targets first.
        key_flags: dict[int, dict[str, dict[str, bool]]] = {}
        for row in column_dictionary_repository().key_columns():
            key_flags.setdefault(row.dataset_id, {})[row.column_name] = {
                "pk": bool(row.is_pk),
                "unique": bool(row.is_unique),
            }
        options = []
        for dataset in datasets:
            if is_internal_dataset(dataset):
                continue
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
                        str(column.column_name): str(getattr(column, "type", None) or "")[:64]
                        for column in dataset.columns
                    },
                    "key_columns": key_flags.get(dataset.id, {}),
                }
            )
        return self.response(200, datasets=options)

    @expose("/dataset/<int:dataset_id>/dictionary", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_dataset_dictionary(self, dataset_id: int):
        """Return dictionary metadata in the same order as the dataset's Superset columns."""
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        try:
            seed_dictionary(dataset)
            dataset_repository = dataset_dictionary_repository()
            rows = column_dictionary_repository().list_for_dataset(dataset_id)
            return self.response(200, **serialize_dictionary(dataset, dataset_repository.get(dataset_id), rows))
        except Exception:
            logger.exception("Could not load dataset dictionary (dataset_id=%s)", dataset_id)
            db.session.rollback()
            return self.response_500(message="Could not load dataset dictionary.")

    @expose("/dataset/<int:dataset_id>/dictionary/suggest", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def suggest_dataset_dictionary(self, dataset_id: int):
        """Stream and persist dataset-level and column-level dictionary suggestions."""
        require_admin()

        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        if not dataset.columns:
            raise NoColumnsToDescribeError()
        try:
            get_chat_model()
        except RuntimeError as ex:
            # A missing API key would otherwise surface only as a generic error in the middle of the stream.
            logger.error("AI AutoFill unavailable: %s", ex)
            raise AutoFillUnavailableError(str(ex)) from ex

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
        seed_dictionary(dataset)
        if not claim_suggestion(dataset_id):
            raise SuggestionInProgressError()
        column_repository = column_dictionary_repository()
        dataset_repository = dataset_dictionary_repository()

        @stream_with_context
        def events():
            try:
                yield sse_event("status", {"total": total, "processed": 0, "message": "Đang chuẩn bị gợi ý"})
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
                    yield sse_event(
                        "suggestions",
                        {
                            "suggestions": saved_suggestions,
                            "processed": processed,
                            "total": total,
                        },
                    )
                    yield sse_event(
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
                yield sse_event(
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
                yield sse_event("done", {"processed": processed, "total": total})
            except Exception as ex:
                db.session.rollback()
                logger.exception("Column dictionary agent failed (dataset_id=%s)", dataset_id)
                status_code = getattr(ex, "status_code", None)
                if status_code == 402:
                    message = (
                        "OpenRouter từ chối yêu cầu vì hết hạn mức credit của API key. "
                        "Nạp thêm credit hoặc thử lại sau."
                    )
                elif status_code == 401:
                    message = (
                        "OpenRouter từ chối API key. Kiểm tra OPENROUTER_API_KEY trong file .env ở thư mục gốc repo."
                    )
                else:
                    message = "Không thể tạo gợi ý từ điển cột."
                # Batches saved before the failure are already committed and shown; only the rest is missing.
                yield sse_event("error", {"message": message})
            finally:
                release_suggestion(dataset_id)

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @expose("/dataset/<int:dataset_id>/dictionary", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_dataset_dictionary(self, dataset_id: int):
        """Bulk update editable dictionary metadata for columns in a Superset dataset."""
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        actual_column_names = {str(column.column_name) for column in dataset.columns}
        payload = request.get_json(silent=True)
        updates = validate_dictionary_payload(payload, actual_column_names, dataset_id)

        dataset_updates = payload.get("dataset", {})
        if not isinstance(dataset_updates, dict):
            raise DataDictionaryValidationError("dataset must be an object.")
        time_updates = {field: dataset_updates.pop(field) for field in DATASET_TIME_FIELDS if field in dataset_updates}
        if "indicator_model" in dataset_updates:
            indicator_model = checked_indicator_model(dataset_updates.pop("indicator_model"), actual_column_names)
            dataset_updates["indicator_model"] = (
                json.dumps(indicator_model, ensure_ascii=False) if indicator_model else None
            )
        for field in ("time_column", "row_kind_column"):
            if time_updates.get(field) == "":
                time_updates[field] = None
        unknown_fields = set(dataset_updates) - DATASET_DICTIONARY_FIELDS
        if unknown_fields:
            raise DataDictionaryValidationError(
                f"dataset contains unsupported fields: {', '.join(sorted(unknown_fields))}."
            )
        for field in ("display_name", "description", "grain", "create_column"):
            if field not in dataset_updates:
                continue
            value = dataset_updates.get(field)
            if field == "display_name":
                if not isinstance(value, str) or not value.strip() or len(value) > 255:
                    raise DataDictionaryValidationError(
                        "dataset.display_name must be a non-empty string of at most 255 characters."
                    )
            elif value is not None and not isinstance(value, str):
                raise DataDictionaryValidationError(f"dataset.{field} must be a string or null.")
        for field in ("description", "grain", "create_column"):
            value = dataset_updates.get(field)
            # A blank value means unset; a stored empty string would read back as a real value.
            if isinstance(value, str) and not value.strip():
                dataset_updates[field] = None
            elif field == "create_column" and isinstance(value, str):
                dataset_updates[field] = value.strip()
        if dataset_updates.get("dataset_type") not in (None, "base", "aggregate"):
            raise DataDictionaryValidationError("dataset.dataset_type must be 'base', 'aggregate', or null.")
        if dataset_updates.get("create_column") and dataset_updates["create_column"] not in actual_column_names:
            raise DataDictionaryValidationError("dataset.create_column must reference a column in this dataset.")
        layer_id = dataset_updates.get("layer_id")
        if layer_id is not None and (
            isinstance(layer_id, bool) or not isinstance(layer_id, int) or data_layer_repository().get(layer_id) is None
        ):
            raise DataDictionaryValidationError("dataset.layer_id must reference an existing data layer or be null.")

        try:
            # Seed first: each seed commits, so it must not run between the updates below and their commit.
            seed_dictionary(dataset)
            for referenced_id in {
                item["referenced_dataset_id"] for item in updates if item.get("referenced_dataset_id") is not None
            } - {dataset_id}:
                seed_dictionary(get_dataset(referenced_id))
            dataset_repository = dataset_dictionary_repository()
            dataset_repository.update(dataset_repository.get(dataset_id), dataset_updates)
            column_repository = column_dictionary_repository()
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
                            raise ReferencedColumnMissingError()
                        update["referenced_column"] = referenced_row.id
                row = column_repository.update(rows_by_name[column_name], update)
                if row.semantic_role != "measure" and row.aggregations:
                    row.aggregations = None
            if time_updates:
                self._save_time_semantics(dataset_repository.get(dataset_id), time_updates, rows_by_name)
            db.session.commit()
            rows = column_repository.list_for_dataset(dataset_id)
            return self.response(200, **serialize_dictionary(dataset, dataset_repository.get(dataset_id), rows))
        except SemanticLayerError:
            raise
        except Exception:
            logger.exception("Could not save dataset dictionary (dataset_id=%s)", dataset_id)
            db.session.rollback()
            return self.response_500(message="Could not save dataset dictionary.")

    @staticmethod
    def _save_time_semantics(
        record: DatasetDictionary,
        time_updates: dict[str, Any],
        rows_by_name: dict[str, ColumnDictionary],
    ) -> None:
        """Store the time column, the row kind column and the grains, checked against the columns as just updated.

        A field left out keeps its stored value; the grains are replaced as a whole.
        """
        grain_repository = dataset_grain_repository()
        stored = grain_repository.list_for_dataset(record.id)
        time_column = time_updates.get("time_column", record.time_column)
        row_kind_column = time_updates.get("row_kind_column", record.row_kind_column)
        grains = time_updates.get("grains")
        if grains is None:
            grains = [
                {"row_kind_value": item.row_kind_value, "label": item.label, "grain": item.grain} for item in stored
            ]
        temporal_kinds = {name: row.temporal_kind for name, row in rows_by_name.items()}
        checked = checked_time_semantics(time_column, row_kind_column, grains, temporal_kinds)
        record.time_column = time_column
        record.row_kind_column = row_kind_column
        grain_repository.replace(stored, record.id, checked)

    @expose("/dataset/<int:dataset_id>/grain-profile", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_grain_profile(self, dataset_id: int):
        """How the time column's values fall for each kind of row, with the grain they suggest.

        Read-only and run only when an administrator asks: one aggregate ChartData query as the caller, so Superset's
        access rules and row-level security apply. `time_column` and `row_kind_column` come from the query string, so
        a choice not saved yet can be profiled.
        """
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        time_column = request.args.get("time_column") or None
        row_kind_column = request.args.get("row_kind_column") or None
        columns = {str(column.column_name): column for column in dataset.columns}
        if time_column not in columns or getattr(columns[time_column], "expression", None):
            raise DataDictionaryValidationError("time_column must be a physical column of this dataset.")
        if row_kind_column is not None and (
            row_kind_column not in columns or getattr(columns[row_kind_column], "expression", None)
        ):
            raise DataDictionaryValidationError("row_kind_column must be a physical column of this dataset.")
        # The kind the administrator sees in the form, which a page not saved yet may still show as its default.
        entry = column_dictionary_repository().get_for_dataset_column(dataset_id, time_column)
        temporal_kind = request.args.get("temporal_kind") or (entry.temporal_kind if entry else None)
        if temporal_kind is None:
            column = columns[time_column]
            temporal_kind = default_temporal_kind(
                getattr(column, "type", None), bool(getattr(column, "is_dttm", False))
            )
        if temporal_kind not in ("date", "timestamp"):
            raise DataDictionaryValidationError("time_column must be a date or timestamp column.")
        payload = build_grain_profile_payload(dataset, time_column, row_kind_column, temporal_kind)
        from superset.charts.schemas import ChartDataQueryContextSchema
        from superset.commands.chart.data.get_data_command import ChartDataCommand

        try:
            command = ChartDataCommand(ChartDataQueryContextSchema().load(payload))
            command.validate()
            result = command.run()["queries"][0]
        except Exception as ex:
            if is_superset_access_error(ex):
                raise DatasetAccessError() from ex
            logger.exception("Reading the grain profile of %s failed", dataset.table_name)
            return self.response_500(message="Could not read the grain profile.")
        if result.get("error"):
            logger.error("Grain profile query of %s failed: %s", dataset.table_name, result["error"])
            return self.response_500(message="Could not read the grain profile.")
        profiles, too_many = grain_profile_from_rows(result.get("data", []), row_kind_column)
        return self.response(
            200,
            time_column=time_column,
            row_kind_column=row_kind_column,
            profiles=profiles,
            too_many_kinds=too_many,
        )

    @staticmethod
    def _read_indicators(dataset: SqlaTable, model: dict[str, Any]) -> dict[str, Any]:
        """The indicators a catalog table names, read through ChartData as the caller. Raises on a failed query."""
        from superset.charts.schemas import ChartDataQueryContextSchema
        from superset.commands.chart.data.get_data_command import ChartDataCommand

        command = ChartDataCommand(ChartDataQueryContextSchema().load(build_indicators_payload(dataset, model)))
        command.validate()
        result = command.run()["queries"][0]
        if result.get("error"):
            raise RuntimeError(result["error"])
        return indicators_from_rows(result.get("data", []), model)

    @expose("/dataset/<int:dataset_id>/indicators", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_indicators(self, dataset_id: int):
        """The indicators of a catalog table, with their aggregation mapped and the codes the map does not cover.

        `model` in the query string previews a catalog declaration not saved yet; without it the stored one is read.
        """
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        column_names = {
            str(column.column_name) for column in dataset.columns if not getattr(column, "expression", None)
        }
        try:
            raw = request.args.get("model")
            model = (
                checked_indicator_model(json.loads(raw), column_names)
                if raw
                else stored_indicator_model(
                    getattr(dataset_dictionary_repository().get(dataset_id), "indicator_model", None)
                )
            )
        except (TypeError, ValueError) as ex:
            raise DataDictionaryValidationError(str(ex)) from ex
        if not model or model["kind"] != "catalog":
            raise NotIndicatorCatalogError()
        try:
            return self.response(200, dataset_id=dataset_id, **self._read_indicators(dataset, model))
        except Exception as ex:
            if is_superset_access_error(ex):
                raise DatasetAccessError() from ex
            logger.exception("Reading the indicators of %s failed", dataset.table_name)
            return self.response_500(message="Could not read the indicators.")
