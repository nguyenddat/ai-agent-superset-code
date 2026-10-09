import json
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from ..core.chat_models import get_chat_model
from .context.agent import BIAgentContext
from .context.contract import BIContract
from .prompts.prompt_bi_planning_agent import system_prompt
from .tools.validate_bi_contract import BIContractValidator, validate_bi_contract
from .context.dashboard import get_dashboard_datasets
from ..core.superset_client import superset_client
from .tools.metadata_catalog import (
    get_column_catalog, get_dataset_catalog,
    get_metric_catalog, get_tool_documentation,
)

planning_agent = create_agent(
    model=get_chat_model(), name="bi-planning-agent",
    tools=[
        get_tool_documentation,
        get_dataset_catalog,
        get_column_catalog,
        get_metric_catalog,
        validate_bi_contract
    ],
    context_schema=BIAgentContext, response_format=BIContract, system_prompt=system_prompt,
)


@dataclass
class BIPlanningResult:
    success: bool
    contract: BIContract | None = None
    errors: list[dict[str, str]] = field(default_factory=list)
    attempts: int = 0


def plan_bi(
    query: str,
    context: BIAgentContext,
    *,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    max_repairs: int = 2,
) -> BIPlanningResult:
    """Create a contract using metadata-only tools, then verify it deterministically."""
    if not query.strip():
        return BIPlanningResult(False, errors=[{"code": "empty_query", "path": "query", "message": "Câu hỏi không được để trống."}])
    context = {**context, "user_question": query}
    allowed_ids = set(context["allowed_dataset_ids"])
    try:
        datasets = get_dashboard_datasets(context["dashboard_id"], superset_client)
        datasets = [dataset for dataset in datasets if dataset.id in allowed_ids]
    except Exception as exc:
        return BIPlanningResult(False, errors=[{"code": "metadata_unavailable", "path": "metadata", "message": str(exc)}])

    errors: list[dict[str, str]] = []
    for attempt in range(max(0, min(max_repairs, 2)) + 1):
        repair = "" if not errors else "\n\nSửa contract theo các lỗi xác thực trước đó:\n" + json.dumps(errors, ensure_ascii=False)
        if on_event:
            on_event("planning_attempt", {"attempt": attempt + 1})
        state = None
        called_validator = False
        inputs = {"messages": [HumanMessage(content=f"Câu hỏi gốc: {query}{repair}")]}
        try:
            for mode, chunk in planning_agent.stream(inputs, context=context, stream_mode=["updates", "values"]):
                if mode == "values":
                    state = chunk
                    continue
                for node, update in chunk.items():
                    for message in update.get("messages", []):
                        if node in {"model", "agent"}:
                            for call in getattr(message, "tool_calls", []):
                                name = call.get("name", "tool")
                                if name == "validate_bi_contract":
                                    called_validator = True
                                if on_event:
                                    on_event("tool_start", {"tool": name})
                        elif getattr(message, "type", "") == "tool":
                            name = getattr(message, "name", "tool")
                            if name == "validate_bi_contract":
                                called_validator = True
                            if on_event:
                                on_event("tool_result", {"tool": name, "output": _tool_summary(message.content)})
            raw_contract = state.get("structured_response") if isinstance(state, dict) else None
            if raw_contract is None:
                errors = [{"code": "missing_contract", "path": "agent", "message": "Agent chưa trả BIContract có cấu trúc."}]
            elif not called_validator:
                errors = [{"code": "validator_not_called", "path": "agent", "message": "Agent chưa gọi validate_bi_contract."}]
            else:
                contract = raw_contract if isinstance(raw_contract, BIContract) else BIContract.model_validate(raw_contract)
                errors = BIContractValidator().validate(
                    contract,
                    datasets,
                    allowed_ids,
                )
                if not errors:
                    return BIPlanningResult(True, contract=contract, attempts=attempt + 1)
        except Exception as exc:
            errors = [{"code": "planning_error", "path": "agent", "message": str(exc)}]
        if on_event:
            on_event("validation_errors", {"attempt": attempt + 1, "errors": errors})
    return BIPlanningResult(False, errors=errors, attempts=max(0, min(max_repairs, 2)) + 1)


def _tool_summary(content: Any) -> str:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            return content[:1200]
    if isinstance(content, dict) and "valid" in content:
        return "Contract hợp lệ." if content["valid"] else json.dumps(content.get("errors", []), ensure_ascii=False)[:1200]
    if isinstance(content, list):
        return f"Đã nhận {len(content)} mục siêu dữ liệu."
    return "Đã hoàn tất thao tác siêu dữ liệu."
