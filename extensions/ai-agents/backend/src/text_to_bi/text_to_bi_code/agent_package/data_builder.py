import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict, Field

from ..core.chat_models import get_chat_model
from ..core.settings import config
from ..core.superset_client import superset_client
from .context.agent import BIAgentContext, DataBuilderContext, MetadataResolutionContext
from .context.dashboard import get_dashboard_datasets
from .context.metadata_resolution import MetadataResolution
from .prompts.prompt_data_builder import system_prompt
from .tools.compile_chat_chart import compile_chat_chart
from .tools.query_sql import query_sql

logger = logging.getLogger(__name__)


class DataBuilderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1, description="Câu SQL SELECT cuối cùng đã chạy thành công bằng query_sql.")


data_builder_agent = create_agent(
    model=get_chat_model(),
    name="data-builder-agent",
    tools=[query_sql, compile_chat_chart],
    context_schema=DataBuilderContext,
    response_format=DataBuilderResponse,
    system_prompt=system_prompt,
)


@dataclass
class DataBuilderOutcome:
    success: bool
    sql: str | None = None
    summary: dict[str, Any] | None = None
    chart_url: str | None = None
    chart_error: str | None = None
    errors: list[dict[str, str]] = field(default_factory=list)
    attempts: int = 0


def build_data(
    metadata_context: MetadataResolutionContext,
    base_context: BIAgentContext,
    resolution: MetadataResolution,
    *,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    max_repairs: int = 2,
) -> DataBuilderOutcome:
    if resolution.status != "ready" or resolution.dataset_id is None:
        return _failure("metadata_not_ready", "metadata_resolution", "Data Builder chỉ chạy sau MetadataResolution status=ready.")
    source_ids = [source.get("dataset_id") for source in metadata_context["data_sources"]]
    if len(source_ids) != 1 or source_ids[0] != resolution.dataset_id:
        return _failure("unsupported_sources", "data_sources", "Data Builder hiện chỉ hỗ trợ một dataset duy nhất, khớp MetadataResolution.")
    if resolution.dataset_id not in base_context["allowed_dataset_ids"]:
        return _failure("unauthorized_dataset", "dataset_id", "Dataset không thuộc dashboard hiện tại.")

    try:
        datasets = get_dashboard_datasets(base_context["dashboard_id"], superset_client)
        dataset = next((item for item in datasets if item.id == resolution.dataset_id), None)
        if dataset is None:
            return _failure("missing_dataset", "dataset_id", "Dataset không còn trong metadata dashboard.")
        detail_response = superset_client.get(
            f"{config.superset_base_url.rstrip('/')}/api/v1/dataset/{dataset.id}", timeout=30
        )
        detail_response.raise_for_status()
        detail = detail_response.json().get("result")
        if not isinstance(detail, dict):
            return _failure("invalid_dataset_metadata", "dataset_id", "Superset không trả metadata dataset hợp lệ.")
        builder_context: DataBuilderContext = {
            "user_id": base_context["user_id"],
            "dashboard_id": base_context["dashboard_id"],
            "allowed_dataset_ids": list(base_context["allowed_dataset_ids"]),
            "dashboard_title": base_context["dashboard_title"],
            "user_question": base_context["user_question"],
            "user_intent_objective": metadata_context["user_intent_objective"],
            "data_sources": metadata_context["data_sources"],
            "combination": metadata_context["combination"],
            "combination_key": metadata_context["combination_key"],
            "time_range": resolution.time_range,
            "time_grain": metadata_context["time_grain"],
            "order_by": metadata_context["order_by"],
            "data_shape": metadata_context["data_shape"],
            "data_grain": metadata_context["data_grain"],
            "x_axis": metadata_context["x_axis"],
            "y_axis": metadata_context["y_axis"],
            "series": metadata_context["series"],
            "time_comparison": metadata_context["time_comparison"],
            "chart_title": metadata_context["chart_title"],
            "metadata_resolution": resolution.model_dump(mode="json"),
            "dataset_id": dataset.id,
            "dataset_name": dataset.name or dataset.datasource_name or str(dataset.id),
            "table_name": detail.get("table_name") or dataset.table_name or "",
            "schema_name": detail.get("schema") or dataset.schema_,
            "column_names": [
                item.column_name
                for item in dataset.columns
                if item.is_queryable is not False and item.is_sensitive is not True
            ],
        }
    except Exception as exc:
        logger.exception("Unable to prepare Data Builder context (dashboard_id=%s)", base_context["dashboard_id"])
        return _failure("dataset_metadata_error", "metadata", f"Không tải được dataset cho Data Builder: {exc}")

    errors: list[dict[str, str]] = []
    attempts_limit = max(0, min(max_repairs, 2)) + 1
    for attempt in range(attempts_limit):
        if on_event:
            on_event("data_builder_attempt", {"attempt": attempt + 1})
        repair = "" if not errors else "\n\nLần trước chưa xác nhận được chart. Giữ nguyên BI Plan và Metadata Resolution; sửa SQL nếu cần theo lỗi, sau đó gọi query_sql và compile_chat_chart lại với cùng SQL:\n" + json.dumps(errors, ensure_ascii=False)
        state: dict[str, Any] | None = None
        pending_sql: list[str] = []
        pending_chart_sql: list[str] = []
        successful_sql: str | None = None
        successful_summary: dict[str, Any] | None = None
        compiled_sql: str | None = None
        compiled_chart_url: str | None = None
        compile_error: str | None = None
        tool_called = False
        try:
            inputs = {"messages": [HumanMessage(content=(
                "Metadata Resolution đã thành công. Sinh và kiểm tra SQL theo context sau:\n"
                + json.dumps(builder_context, ensure_ascii=False, indent=2, default=str)
                + repair
            ))]}
            for mode, chunk in data_builder_agent.stream(
                inputs, context=builder_context, stream_mode=["updates", "values"]
            ):
                if mode == "values":
                    state = chunk
                    continue
                for node, update in chunk.items():
                    for message in update.get("messages", []):
                        if node in {"model", "agent"}:
                            for call in getattr(message, "tool_calls", []):
                                if call.get("name") == "query_sql":
                                    tool_called = True
                                    sql_argument = (call.get("args") or {}).get("sql")
                                    if isinstance(sql_argument, str):
                                        pending_sql.append(sql_argument)
                                    if on_event:
                                        on_event("tool_start", {"tool": "query_sql"})
                                elif call.get("name") == "compile_chat_chart":
                                    sql_argument = (call.get("args") or {}).get("sql")
                                    if isinstance(sql_argument, str):
                                        pending_chart_sql.append(sql_argument)
                                    if on_event:
                                        on_event("tool_start", {"tool": "compile_chat_chart"})
                        elif getattr(message, "type", "") == "tool" and getattr(message, "name", "") == "query_sql":
                            result = _tool_result(message.content)
                            executed_sql = pending_sql.pop(0) if pending_sql else None
                            if result.get("success") is True and executed_sql:
                                successful_sql = executed_sql
                                successful_summary = {
                                    "column_count": result.get("column_count"),
                                    "columns": result.get("columns", []),
                                    "row_count": result.get("row_count"),
                                }
                            else:
                                successful_sql = None
                                successful_summary = None
                            if on_event:
                                on_event("tool_result", {"tool": "query_sql", "output": json.dumps(result, ensure_ascii=False)[:1200]})
                        elif getattr(message, "type", "") == "tool" and getattr(message, "name", "") == "compile_chat_chart":
                            result = _tool_result(message.content)
                            attempted_sql = pending_chart_sql.pop(0) if pending_chart_sql else None
                            if result.get("success") is True and attempted_sql:
                                compiled_sql = attempted_sql
                                compiled_chart_url = result.get("chart_url")
                                compile_error = None
                            else:
                                compiled_sql = None
                                compiled_chart_url = None
                                compile_error = str(result.get("error") or "Superset không trả lỗi chi tiết.")
                            if on_event:
                                on_event("tool_result", {"tool": "compile_chat_chart", "output": json.dumps(result, ensure_ascii=False)[:1200]})

            raw = state.get("structured_response") if isinstance(state, dict) else None
            if not tool_called:
                errors = [_issue("query_tool_not_called", "agent", "Data Builder phải gọi query_sql trước khi trả SQL cuối cùng.")]
            elif successful_sql is None:
                errors = [_issue("query_failed", "query_sql", "query_sql chưa chạy thành công; xem lỗi tool và sửa SQL rồi gọi lại.")]
            elif compiled_sql is None:
                errors = [_issue("chart_not_compiled", "compile_chat_chart", compile_error or "Data Builder phải gọi compile_chat_chart bằng đúng SQL query_sql vừa chạy thành công và sửa theo lỗi nếu compile thất bại.")]
            elif raw is None:
                errors = [_issue("missing_sql", "agent", "Data Builder chưa trả SQL cuối cùng có cấu trúc.")]
            else:
                final = raw if isinstance(raw, DataBuilderResponse) else DataBuilderResponse.model_validate(raw)
                if _normalise_sql(final.sql) != _normalise_sql(successful_sql) or _normalise_sql(final.sql) != _normalise_sql(compiled_sql):
                    errors = [_issue("final_sql_not_validated", "sql", "Đầu ra phải giữ nguyên câu SQL đã chạy thành công bằng query_sql và compile_chat_chart.")]
                else:
                    final_sql = successful_sql.strip().rstrip(";")
                    return DataBuilderOutcome(
                        True,
                        sql=final_sql,
                        summary=successful_summary,
                        chart_url=compiled_chart_url,
                        attempts=attempt + 1,
                    )
        except Exception as exc:
            logger.exception("Data Builder attempt failed (dashboard_id=%s)", base_context["dashboard_id"])
            errors = [_issue("data_builder_error", "agent", str(exc))]
        if on_event:
            on_event("data_builder_validation_errors", {"attempt": attempt + 1, "errors": errors})

    return DataBuilderOutcome(False, errors=errors, attempts=attempts_limit)


def _tool_result(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            value = json.loads(content)
            return value if isinstance(value, dict) else {"success": False, "error": "Tool trả kết quả không hợp lệ."}
        except ValueError:
            return {"success": False, "error": content[:1200]}
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                return _tool_result(item["text"])
    return {"success": False, "error": "Tool không trả kết quả JSON hợp lệ."}


def _normalise_sql(sql: str) -> str:
    return " ".join(sql.strip().rstrip(";").split())


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _failure(code: str, path: str, message: str) -> DataBuilderOutcome:
    return DataBuilderOutcome(False, errors=[_issue(code, path, message)])
