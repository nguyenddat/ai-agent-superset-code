"""Compile a chart from Data Builder SQL using Superset's native query pipeline."""

import logging
from typing import Any

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, ConfigDict, Field

from ..context.agent import BIAgentContext, DataBuilderContext, MetadataResolutionContext
from ..context.metadata_resolution import MetadataResolution
from ..superset_chart import create_chat_chart

logger = logging.getLogger(__name__)


class CompileChatChartInput(BaseModel):
    # LangGraph injects the trusted ToolRuntime argument internally; ignore it
    # in the public schema validation, matching query_sql's input model.
    model_config = ConfigDict(extra="ignore")

    sql: str = Field(min_length=1, max_length=50000, description="SQL vừa chạy thành công qua query_sql.")


@tool(args_schema=CompileChatChartInput)
def compile_chat_chart(sql: str, runtime: ToolRuntime) -> dict[str, Any]:
    """Validate the supplied SQL and compile a chart on the existing Superset dataset."""
    try:
        context = runtime.context or {}
        metadata_context: MetadataResolutionContext = {
            key: context[key]
            for key in (
                "user_id", "dashboard_id", "allowed_dataset_ids", "dashboard_title",
                "user_question", "user_intent_objective", "data_sources", "combination",
                "combination_key", "time_range", "time_grain", "order_by", "data_shape",
                "data_grain", "x_axis", "y_axis", "series", "time_comparison", "chart_title",
            )
        }
        base_context: BIAgentContext = {
            key: context[key]
            for key in ("user_id", "dashboard_id", "allowed_dataset_ids", "dashboard_title", "user_question")
        }
        resolution = MetadataResolution.model_validate(context.get("metadata_resolution"))
        chart_url, error = create_chat_chart(sql, metadata_context, base_context, resolution)
        if error:
            return {"success": False, "error": error[:1500]}
        return {"success": True, "chart_url": chart_url}
    except Exception as exc:
        logger.exception("Data Builder chart compile tool failed")
        return {"success": False, "error": f"Lỗi compile chart {type(exc).__name__}: {str(exc)[:1200]}"}
