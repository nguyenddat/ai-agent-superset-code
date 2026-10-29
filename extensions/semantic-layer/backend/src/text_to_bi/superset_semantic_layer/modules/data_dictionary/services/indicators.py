import json
import re
from typing import Any

from ..exceptions import DataDictionaryValidationError

INDICATOR_KINDS = ("values", "catalog")
INDICATOR_AGGREGATIONS = ("SUM", "AVG", "MIN", "MAX", "COUNT", "NONE")
CATALOG_COLUMNS = ("key_column", "code_column", "name_column", "unit_column", "value_kind_column", "aggregation_column")
REQUIRED_CATALOG_COLUMNS = ("key_column", "code_column", "name_column")
MAX_INDICATORS = 500
MAX_CODES = 20
MAX_CODE_LENGTH = 60
SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _checked_column(value: Any, field: str, column_names: set[str], required: bool) -> str | None:
    if value in (None, ""):
        if required:
            raise DataDictionaryValidationError(f"dataset.indicator_model.{field} is required.")
        return None
    if not isinstance(value, str) or value not in column_names:
        raise DataDictionaryValidationError(f"dataset.indicator_model.{field} must be a column of this dataset.")
    return value


def _checked_codes(value: Any, field: str, allowed: tuple[str, ...] | None, column_names: set[str]) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_CODES:
        raise DataDictionaryValidationError(f"dataset.indicator_model.{field} must map at most {MAX_CODES} codes.")
    checked = {}
    for code, target in value.items():
        if not isinstance(code, str) or not code or len(code) > MAX_CODE_LENGTH:
            raise DataDictionaryValidationError(
                f"dataset.indicator_model.{field} has a code that is not a short string."
            )
        if allowed is not None and target not in allowed:
            raise DataDictionaryValidationError(
                f"dataset.indicator_model.{field}.{code} must be one of {', '.join(allowed)}."
            )
        if allowed is None and target not in column_names:
            raise DataDictionaryValidationError(
                f"dataset.indicator_model.{field}.{code} must be a column of this dataset."
            )
        checked[code] = target
    return checked


def checked_indicator_model(model: Any, column_names: set[str]) -> dict[str, Any] | None:
    """The declaration to store, checked against the dataset's columns; None clears it. Raises ValueError."""
    if model is None:
        return None
    if not isinstance(model, dict) or model.get("kind") not in INDICATOR_KINDS:
        raise DataDictionaryValidationError(
            "dataset.indicator_model must be null or an object whose kind is 'values' or 'catalog'."
        )
    if model["kind"] == "values":
        if set(model) - {"kind", "indicator_column", "value_columns"}:
            raise DataDictionaryValidationError(
                "A values indicator_model holds only indicator_column and value_columns."
            )
        value_columns = _checked_codes(model.get("value_columns"), "value_columns", None, column_names)
        if not value_columns:
            raise DataDictionaryValidationError(
                "dataset.indicator_model.value_columns needs the value column of at least one value kind."
            )
        indicator_column = _checked_column(model.get("indicator_column"), "indicator_column", column_names, True)
        if indicator_column in value_columns.values():
            raise DataDictionaryValidationError("The indicator column cannot also hold values.")
        return {"kind": "values", "indicator_column": indicator_column, "value_columns": value_columns}
    if set(model) - {"kind", *CATALOG_COLUMNS, "aggregation_map"}:
        raise DataDictionaryValidationError("A catalog indicator_model holds only its columns and aggregation_map.")
    checked: dict[str, Any] = {"kind": "catalog"}
    for field in CATALOG_COLUMNS:
        checked[field] = _checked_column(model.get(field), field, column_names, field in REQUIRED_CATALOG_COLUMNS)
    checked["aggregation_map"] = _checked_codes(
        model.get("aggregation_map"), "aggregation_map", INDICATOR_AGGREGATIONS, column_names,
    )
    if checked["aggregation_map"] and not checked["aggregation_column"]:
        raise DataDictionaryValidationError("dataset.indicator_model.aggregation_map needs an aggregation_column.")
    return checked


def stored_indicator_model(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        model = json.loads(value)
    except (TypeError, ValueError):
        return None
    return model if isinstance(model, dict) and model.get("kind") in INDICATOR_KINDS else None


def build_indicators_payload(dataset: Any, model: dict[str, Any]) -> dict[str, Any]:
    """The only ChartData query the indicator list runs: the catalog's declared columns, grouped, bounded."""
    columns = [model[field] for field in CATALOG_COLUMNS if model.get(field)]
    if any(not SIMPLE_IDENTIFIER.match(name) for name in columns):
        raise DataDictionaryValidationError("Indicator columns must be plainly named.")
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [{
            "columns": list(dict.fromkeys(columns)),
            "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "row_count"}],
            "row_limit": MAX_INDICATORS + 1,
        }],
        "result_type": "full",
        "result_format": "json",
    }


def indicators_from_rows(rows: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    """Each indicator with its aggregation mapped, the aggregation codes found, and whether there were more indicators
    than the list keeps."""
    def value(row: dict[str, Any], field: str) -> Any:
        return row.get(model[field]) if model.get(field) else None

    aggregation_map = model.get("aggregation_map") or {}
    indicators = []
    for row in rows[:MAX_INDICATORS]:
        if value(row, "key_column") is None:
            continue
        code = value(row, "aggregation_column")
        indicators.append({
            "key": value(row, "key_column"),
            "code": value(row, "code_column"),
            "name": value(row, "name_column"),
            "unit": value(row, "unit_column"),
            "value_kind": value(row, "value_kind_column"),
            "aggregation_code": code,
            "aggregation": aggregation_map.get(str(code)) if code is not None else None,
        })
    indicators.sort(key=lambda item: str(item["code"] or item["key"]))
    aggregation_codes = {str(item["aggregation_code"]) for item in indicators if item["aggregation_code"] is not None}
    return {
        "indicators": indicators, "aggregation_codes": sorted(aggregation_codes),
        "too_many": len(rows) > MAX_INDICATORS,
    }


def read_indicators(dataset: Any, model: dict[str, Any]) -> dict[str, Any]:
    """The indicators a catalog table names, read through ChartData as the caller. Raises on a failed query."""
    from superset.charts.schemas import ChartDataQueryContextSchema
    from superset.commands.chart.data.get_data_command import ChartDataCommand

    command = ChartDataCommand(ChartDataQueryContextSchema().load(build_indicators_payload(dataset, model)))
    command.validate()
    result = command.run()["queries"][0]
    if result.get("error"):
        raise RuntimeError(result["error"])
    return indicators_from_rows(result.get("data", []), model)
