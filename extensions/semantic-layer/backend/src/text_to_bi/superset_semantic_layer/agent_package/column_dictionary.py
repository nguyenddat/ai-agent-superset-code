import json
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from ..core.chat_models import get_chat_model
from .prompts.prompt_column_dictionary import system_prompt
from .prompts.prompt_dataset_dictionary import dataset_system_prompt


class ColumnDictionarySuggestion(BaseModel):
    column_name: str = Field(description="Tên cột vật lý, giữ nguyên như đầu vào.")
    display_name: str = Field(description="Nhãn dễ hiểu bằng tiếng Việt, tối đa 255 ký tự.")
    unit: str | None = Field(
        default=None,
        description="Đơn vị đo nếu biết chắc, nếu không thì null.",
    )
    business_term: str | None = Field(
        default=None,
        description="Mô tả nghiệp vụ ngắn nếu đủ căn cứ, nếu không thì null.",
    )


class ColumnDictionarySuggestions(BaseModel):
    suggestions: list[ColumnDictionarySuggestion] = Field(
        description="Đề xuất cho toàn bộ cột được gửi vào, mỗi tên cột xuất hiện đúng một lần."
    )


class DatasetDictionarySuggestion(BaseModel):
    display_name: str = Field(description="Tên hiển thị ngắn gọn, dễ hiểu bằng tiếng Việt.")
    description: str | None = Field(default=None, description="Mô tả dataset, null nếu thiếu căn cứ.")
    grain: str | None = Field(default=None, description="Mức độ chi tiết của một bản ghi, null nếu chưa rõ.")
    create_column: str | None = Field(
        default=None,
        description="Tên cột phù hợp nhất để xác định thời điểm/tạo bản ghi, phải khớp tên cột đầu vào hoặc null.",
    )


@lru_cache(maxsize=1)
def _get_agent():
    return create_agent(
        model=get_chat_model(),
        name="column-dictionary-agent",
        tools=[],
        response_format=ColumnDictionarySuggestions,
        system_prompt=system_prompt,
    )


@lru_cache(maxsize=1)
def _get_dataset_agent():
    return create_agent(
        model=get_chat_model(),
        name="dataset-dictionary-agent",
        tools=[],
        response_format=DatasetDictionarySuggestion,
        system_prompt=dataset_system_prompt,
    )


def suggest_dataset_dictionary(dataset: dict[str, Any]) -> dict[str, Any]:
    """Suggest dataset-level descriptive metadata and an optional record column."""
    result = _get_dataset_agent().invoke({
        "messages": [HumanMessage(content=json.dumps(dataset, ensure_ascii=False, indent=2))]
    })
    raw = result.get("structured_response") if isinstance(result, dict) else None
    if raw is None:
        raise RuntimeError("Agent không trả về structured response cho dataset.")
    suggestion = raw if isinstance(raw, DatasetDictionarySuggestion) else DatasetDictionarySuggestion.model_validate(raw)
    suggestion.display_name = suggestion.display_name.strip()
    if not suggestion.display_name or len(suggestion.display_name) > 255:
        raise ValueError("Agent trả display_name dataset không hợp lệ.")
    if suggestion.description is not None:
        suggestion.description = suggestion.description.strip()[:4000] or None
    if suggestion.grain is not None:
        suggestion.grain = suggestion.grain.strip()[:2000] or None
    if suggestion.create_column is not None:
        suggestion.create_column = suggestion.create_column.strip() or None
        valid_columns = {str(column["column_name"]) for column in dataset.get("columns", [])}
        if suggestion.create_column not in valid_columns:
            raise ValueError("Agent trả create_column không thuộc dataset.")
    return suggestion.model_dump(mode="json")


def _suggest_column_batch(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate only display name, unit, and business term suggestions for one batch."""
    agent = _get_agent()
    result = agent.invoke({
        "messages": [HumanMessage(content=json.dumps(dataset, ensure_ascii=False, indent=2))]
    })
    raw = result.get("structured_response") if isinstance(result, dict) else None
    if raw is None:
        raise RuntimeError("Agent không trả về structured response.")
    response = raw if isinstance(raw, ColumnDictionarySuggestions) else ColumnDictionarySuggestions.model_validate(raw)
    expected_names = [item["column_name"] for item in dataset["columns"]]
    suggestions = response.suggestions
    suggested_names = [suggestion.column_name for suggestion in suggestions]
    if len(suggested_names) != len(set(suggested_names)) or set(suggested_names) != set(expected_names):
        raise ValueError("Agent trả về thiếu, trùng hoặc dư column_name.")

    for suggestion in suggestions:
        suggestion.display_name = suggestion.display_name.strip()
        if not suggestion.display_name or len(suggestion.display_name) > 255:
            raise ValueError(f"Agent trả display_name không hợp lệ cho {suggestion.column_name}.")
        if suggestion.unit is not None:
            suggestion.unit = suggestion.unit.strip()[:128] or None
        if suggestion.business_term is not None:
            suggestion.business_term = suggestion.business_term.strip()[:2000] or None
    return [suggestion.model_dump(mode="json") for suggestion in suggestions]


def suggest_column_dictionary_batches(
    dataset: dict[str, Any], batch_size: int = 4
) -> Iterator[list[dict[str, Any]]]:
    """Generate suggestions in small independent batches for incremental streaming."""
    columns = dataset.get("columns")
    if not isinstance(columns, list):
        raise ValueError("Dataset context must contain a columns list.")  # noqa: TRY004
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")

    for start in range(0, len(columns), batch_size):
        batch_context = {**dataset, "columns": columns[start : start + batch_size]}
        yield _suggest_column_batch(batch_context)


def suggest_column_dictionary(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate only display name, unit, and business term suggestions for dataset columns."""
    return [suggestion for batch in suggest_column_dictionary_batches(dataset) for suggestion in batch]
