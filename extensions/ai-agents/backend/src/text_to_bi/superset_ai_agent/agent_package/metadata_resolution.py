import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from ..core.chat_models import get_chat_model
from ..core.superset_client import superset_client
from .context.agent import BIAgentContext, MetadataResolutionContext
from .context.contract import BIContract
from .context.dashboard import get_dashboard_datasets
from .context.metadata_resolution import MetadataResolution
from .prompts.prompt_metadata_resolution import system_prompt
from .tools.chart_capabilities import (
    get_superset_chart_type_schema,
    get_superset_chart_types,
)
from .tools.metadata_catalog import get_tool_documentation
from .tools.validate_metadata_resolution import (
    validate_metadata_resolution as validate_metadata_resolution_tool,
    validate_metadata_resolution_contract,
    _planned_time_range,
)

logger = logging.getLogger(__name__)


metadata_resolution_agent = create_agent(
    model=get_chat_model(), name="metadata-resolution-agent",
    tools=[
        get_tool_documentation,
        get_superset_chart_types,
        get_superset_chart_type_schema,
        validate_metadata_resolution_tool,
    ],
    context_schema=MetadataResolutionContext, response_format=MetadataResolution,
    system_prompt=system_prompt,
)


@dataclass
class MetadataResolutionOutcome:
    success: bool
    resolution: MetadataResolution | None = None
    errors: list[dict[str, str]] = field(default_factory=list)
    attempts: int = 0
    agent_context: MetadataResolutionContext | None = None


def resolve_metadata(
    contract: BIContract,
    context: BIAgentContext,
    *,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    max_repairs: int = 2,
) -> MetadataResolutionOutcome:
    """Resolve chart metadata/config only; never execute a query or create a chart."""
    source_ids = [source.dataset_id for source in contract.data_resolve.sources]
    allowed_ids = set(context["allowed_dataset_ids"])
    if len(source_ids) != 1:
        return _unsupported(
            "MetadataResolution hiện chỉ có thể tạo cấu hình chart cho một dataset. "
            "BI Plan đang có nhiều nguồn; cần schema dữ liệu đã chuẩn hóa trước khi chọn cấu hình chung."
        )
    dataset_id = source_ids[0]
    if dataset_id not in allowed_ids:
        return _failure("unauthorized_dataset", "data_resolve.sources", f"Dataset {dataset_id} không được dashboard cho phép.")

    try:
        datasets = get_dashboard_datasets(context["dashboard_id"], superset_client)
        datasets = [dataset for dataset in datasets if dataset.id in allowed_ids]
    except Exception as exc:
        return _failure("metadata_unavailable", "metadata", f"Không tải được metadata dashboard: {exc}")
    dataset = next((item for item in datasets if item.id == dataset_id), None)
    if dataset is None:
        return _failure("missing_dataset", "data_resolve.sources[0].dataset_id", f"Dataset {dataset_id} không có trong metadata dashboard.")

    errors: list[dict[str, str]] = []
    plan_fields = _metadata_resolution_context(contract, context)
    for attempt in range(max(0, min(max_repairs, 2)) + 1):
        if on_event:
            on_event("metadata_attempt", {"attempt": attempt + 1})
        repair = "" if not errors else "\n\nSửa cấu hình theo lỗi xác thực sau đây:\n" + json.dumps(errors, ensure_ascii=False)
        state: dict[str, Any] | None = None
        called_tools: set[str] = set()
        try:
            inputs = {
                "messages": [HumanMessage(content=(
                    "BI Plan đã xác thực, được tách thành các trường:\n"
                    + json.dumps(plan_fields, ensure_ascii=False, indent=2)
                    + repair
                ))]
            }
            for mode, chunk in metadata_resolution_agent.stream(
                inputs, context=plan_fields, stream_mode=["updates", "values"]
            ):
                if mode == "values":
                    state = chunk
                    continue
                for node, update in chunk.items():
                    for message in update.get("messages", []):
                        if node in {"model", "agent"}:
                            for call in getattr(message, "tool_calls", []):
                                name = call.get("name", "tool")
                                if on_event:
                                    on_event("tool_start", {"tool": name})
                        elif getattr(message, "type", "") == "tool":
                            name = getattr(message, "name", "tool")
                            called_tools.add(name)
                            if getattr(message, "status", None) == "error":
                                detail = str(message.content)
                                for marker in (" with error:\n", " with error: "):
                                    if marker in detail:
                                        detail = detail.split(marker, 1)[1]
                                        break
                                logger.error(
                                    "MetadataResolution tool invocation failed (dashboard_id=%s, tool=%s): %s",
                                    context["dashboard_id"], name, detail[:3000],
                                )
                            if on_event:
                                on_event("tool_result", {
                                    "tool": name,
                                    "output": str(message.content)[:1200],
                                })

            raw = state.get("structured_response") if isinstance(state, dict) else None
            if raw is None:
                errors = [_issue("missing_resolution", "metadata_resolution", "Agent chưa trả cấu hình có cấu trúc.")]
            elif not {"get_superset_chart_types", "get_superset_chart_type_schema", "validate_metadata_resolution"}.issubset(called_tools):
                errors = [_issue("required_tools_not_called", "metadata_resolution", "Agent phải đọc chart registry, JSON Schema và gọi validate_metadata_resolution trước khi hoàn tất.")]
            else:
                resolution = raw if isinstance(raw, MetadataResolution) else MetadataResolution.model_validate(raw)
                if resolution.status == "unsupported":
                    errors = validate_metadata_resolution_contract(contract, resolution, dataset)
                    if not errors:
                        return MetadataResolutionOutcome(False, resolution=resolution, attempts=attempt + 1)
                else:
                    errors = validate_metadata_resolution_contract(contract, resolution, dataset)
                if not errors:
                    return MetadataResolutionOutcome(
                        True, resolution=resolution, attempts=attempt + 1, agent_context=plan_fields
                    )
        except Exception as exc:
            errors = [_issue("resolution_error", "metadata_resolution", str(exc))]
        if on_event:
            on_event("metadata_validation_errors", {"attempt": attempt + 1, "errors": errors})
    message = "Không thể tạo cấu hình biểu đồ hợp lệ: " + "; ".join(item["message"] for item in errors)
    return MetadataResolutionOutcome(
        False,
        resolution=MetadataResolution(status="unsupported", message=message),
        errors=errors,
        attempts=max(0, min(max_repairs, 2)) + 1,
    )



def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _metadata_resolution_context(
    contract: BIContract, context: BIAgentContext
) -> MetadataResolutionContext:
    return {
        "user_id": context["user_id"],
        "dashboard_id": context["dashboard_id"],
        "allowed_dataset_ids": list(context["allowed_dataset_ids"]),
        "dashboard_title": context["dashboard_title"],
        "user_question": context["user_question"],
        "user_intent_objective": contract.user_intent.objective,
        "data_sources": [source.model_dump(mode="json") for source in contract.data_resolve.sources],
        "combination": contract.data_resolve.combination,
        "combination_key": list(contract.data_resolve.combination_key),
        "time_range": _planned_time_range(contract, []),
        "time_grain": contract.data_resolve.time_grain,
        "order_by": list(contract.data_resolve.order_by),
        "data_shape": contract.chart_resolve.data_shape,
        "data_grain": contract.chart_resolve.data_grain,
        "x_axis": contract.chart_resolve.x_axis,
        "y_axis": list(contract.chart_resolve.y_axis),
        "series": contract.chart_resolve.series,
        "time_comparison": contract.chart_resolve.time_comparison,
        "chart_title": contract.chart_resolve.title,
    }


def _failure(code: str, path: str, message: str) -> MetadataResolutionOutcome:
    resolution = MetadataResolution(status="unsupported", message=message)
    return MetadataResolutionOutcome(False, resolution=resolution, errors=[_issue(code, path, message)])


def _unsupported(message: str) -> MetadataResolutionOutcome:
    result = MetadataResolution(status="unsupported", message=message)
    return MetadataResolutionOutcome(False, resolution=result)
