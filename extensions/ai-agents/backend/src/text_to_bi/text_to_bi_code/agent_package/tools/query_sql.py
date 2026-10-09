import logging
import re
import secrets
from typing import Any

import sqlglot
from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp

from ...core.settings import config
from ...core.superset_client import superset_client
from ..context.dashboard import get_dashboard_datasets

logger = logging.getLogger(__name__)


class QuerySQLInput(BaseModel):
    # LangGraph supplies a trusted runtime object beyond the public SQL input.
    model_config = ConfigDict(extra="ignore")

    sql: str = Field(min_length=1, max_length=50000, description="Một câu SELECT trên dataset trong dashboard hiện tại.")


def _dialect(backend: str | None) -> str | None:
    normalized = (backend or "").casefold()
    return {
        "postgresql": "postgres",
        "postgres": "postgres",
        "mysql": "mysql",
        "mariadb": "mysql",
        "sqlite": "sqlite",
        "snowflake": "snowflake",
        "bigquery": "bigquery",
        "redshift": "redshift",
        "trino": "trino",
        "presto": "presto",
        "duckdb": "duckdb",
    }.get(normalized)


def _dataset_detail(dataset_id: int, dashboard_id: int, allowed_ids: list[int]) -> dict[str, Any] | dict[str, str]:
    if dataset_id not in allowed_ids:
        return {"error": "Dataset không thuộc dashboard hiện tại."}
    datasets = get_dashboard_datasets(dashboard_id, superset_client)
    dataset = next((item for item in datasets if item.id == dataset_id), None)
    if dataset is None:
        return {"error": "Dataset không còn trong dashboard; hãy lập lại context rồi thử lại."}
    response = superset_client.get(
        f"{config.superset_base_url.rstrip('/')}/api/v1/dataset/{dataset_id}", timeout=30
    )
    response.raise_for_status()
    result = response.json().get("result")
    if not isinstance(result, dict):
        return {"error": "Superset không trả metadata dataset hợp lệ."}
    result["_dashboard_dataset"] = dataset
    return result


def _prepare_sql(sql: str, detail: dict[str, Any], dialect: str) -> tuple[str | None, str | None]:
    try:
        parsed_statements = sqlglot.parse(sql, read=dialect)
    except Exception as exc:
        return None, f"Không phân tích được SQL ({type(exc).__name__}): {exc}"
    if len(parsed_statements) != 1 or not isinstance(parsed_statements[0], exp.Select):
        return None, "Chỉ chấp nhận đúng một câu SELECT. Hãy sửa SQL rồi gọi lại query_sql."

    query = parsed_statements[0]
    if any(isinstance(node, (exp.Subquery, exp.CTE, exp.Union, exp.Intersect, exp.Except)) for node in query.walk()):
        return None, "SELECT chỉ được đọc trực tiếp một dataset; không dùng CTE, subquery hoặc set operation."

    dataset = detail["_dashboard_dataset"]
    table_name = (detail.get("table_name") or dataset.table_name or "").casefold()
    schema_name = (detail.get("schema") or dataset.schema_ or "").casefold()
    tables = list(query.find_all(exp.Table))
    if len(tables) != 1:
        return None, "SQL phải đọc đúng một lần từ dataset hiện tại."
    source_table = tables[0]
    if source_table.name.casefold() != table_name:
        return None, f"SQL chỉ được đọc dataset '{table_name}', không được đọc bảng '{source_table.name}'."
    if source_table.db and source_table.db.casefold() != schema_name:
        return None, f"SQL phải dùng schema của dataset ({schema_name or 'mặc định'})."

    allowed_columns = {
        column.column_name.casefold()
        for column in dataset.columns
        if column.is_queryable is not False and column.is_sensitive is not True
    }
    output_aliases = {
        projection.alias.casefold()
        for projection in query.expressions
        if isinstance(projection, exp.Expression) and projection.alias
    }
    for column in query.find_all(exp.Column):
        name = column.name.casefold()
        if name and name != "*" and name not in allowed_columns and name not in output_aliases:
            return None, f"Cột '{column.name}' không thuộc danh sách cột được phép của dataset."

    blocked_functions = {"nextval", "setval", "set_config"}
    for function in query.find_all(exp.Func):
        function_name = (function.name or function.sql_name()).casefold()
        if (
            function_name in blocked_functions
            or function_name.startswith(("pg_", "dblink", "lo_"))
        ):
            return None, f"Hàm '{function_name}' không được phép trong truy vấn Data Builder."

    # A virtual dataset is expanded only after validation, so the model cannot
    # replace its trusted source SQL or introduce a different physical table.
    source_sql = detail.get("sql")
    if source_sql:
        try:
            source_query = sqlglot.parse_one(source_sql, read=dialect)
        except Exception as exc:
            return None, f"Không thể đọc SQL nguồn đã lưu trong Superset ({type(exc).__name__})."
        alias = source_table.args.get("alias")
        table_alias = alias.copy() if alias else exp.TableAlias(this=exp.to_identifier(source_table.name))
        source_table.replace(exp.Subquery(this=source_query, alias=table_alias))

    return query.sql(dialect=dialect), None


def _request_sql(database_id: int, sql: str) -> dict[str, Any]:
    response = superset_client.post(
        f"{config.superset_base_url.rstrip('/')}/api/v1/sqllab/execute/",
        json={
            "database_id": database_id,
            "sql": sql,
            "client_id": secrets.token_urlsafe(8)[:11],
            "queryLimit": 1,
            "runAsync": False,
            "expand_data": False,
        },
        timeout=90,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok or payload.get("errors"):
        errors = payload.get("errors") or []
        message = errors[0].get("message") if errors and isinstance(errors[0], dict) else None
        message = message or payload.get("message") or f"SQL Lab trả HTTP {response.status_code}."
        return {"error": str(message)[:1500]}
    query = payload.get("query") or {}
    if query.get("errorMessage"):
        return {"error": str(query["errorMessage"])[:1500]}
    return payload


@tool(args_schema=QuerySQLInput)
def query_sql(sql: str, runtime: ToolRuntime) -> dict[str, Any]:
    """Chạy SQL do Data Builder tạo và chỉ trả schema kết quả cùng số dòng, không trả dữ liệu raw."""
    context = runtime.context or {}
    dataset_id = context.get("dataset_id")
    dashboard_id = context.get("dashboard_id")
    allowed_ids = context.get("allowed_dataset_ids", [])
    if not isinstance(dataset_id, int) or not isinstance(dashboard_id, int):
        return {"success": False, "error": "Thiếu dataset hoặc dashboard trong runtime context đáng tin cậy."}

    try:
        detail = _dataset_detail(dataset_id, dashboard_id, allowed_ids)
        if "error" in detail:
            return {"success": False, "error": detail["error"]}
        backend = (detail.get("database") or {}).get("backend")
        dialect = _dialect(backend)
        if not dialect:
            return {"success": False, "error": f"Data Builder chưa hỗ trợ SQL dialect '{backend}'."}
        prepared_sql, error = _prepare_sql(sql, detail, dialect)
        if error:
            return {"success": False, "error": error}

        database_id = (detail.get("database") or {}).get("id")
        if not isinstance(database_id, int):
            return {"success": False, "error": "Dataset không có database_id hợp lệ trong metadata Superset."}

        # LIMIT 0 asks SQL Lab for the result schema without transferring any
        # result rows. The second query returns only a single COUNT aggregate.
        schema_result = _request_sql(database_id, f"SELECT * FROM ({prepared_sql}) AS __text_to_bi_result LIMIT 0")
        if "error" in schema_result:
            return {"success": False, "error": schema_result["error"]}
        columns = [
            {"name": column.get("name"), "type": column.get("type")}
            for column in schema_result.get("columns", [])
            if isinstance(column, dict) and column.get("name")
        ]
        count_result = _request_sql(
            database_id,
            f"SELECT COUNT(*) AS __text_to_bi_row_count FROM ({prepared_sql}) AS __text_to_bi_result",
        )
        if "error" in count_result:
            return {"success": False, "error": count_result["error"]}
        data = count_result.get("data") or []
        row_count: int | None = None
        if data and isinstance(data[0], dict):
            value = data[0].get("__text_to_bi_row_count")
            if value is None and data[0]:
                value = next(iter(data[0].values()))
            try:
                row_count = int(value)
            except (TypeError, ValueError):
                pass
        if row_count is None or not columns:
            return {"success": False, "error": "SQL đã chạy nhưng Superset không trả đủ tên cột hoặc số dòng để xác nhận kết quả."}
        return {
            "success": True,
            "column_count": len(columns),
            "columns": columns,
            "row_count": row_count,
        }
    except Exception as exc:
        logger.exception("Data Builder query failed (dashboard_id=%s, dataset_id=%s)", dashboard_id, dataset_id)
        return {"success": False, "error": f"Lỗi truy vấn {type(exc).__name__}: {str(exc)[:1000]}"}
