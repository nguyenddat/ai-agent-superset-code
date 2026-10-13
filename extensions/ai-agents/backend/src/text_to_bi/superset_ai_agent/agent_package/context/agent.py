from typing import Any, TypedDict


class AnalysisMetric(TypedDict):
    name: str
    aggregation: str | None


class AnalysisFilter(TypedDict):
    field: str
    operator: str | None
    value: str


class AgentContext(TypedDict):
    user_id: int
    dashboard_id: int
    dashboard_title: str
    allowed_dataset_ids: list[int]
    analysis_summary: str
    analysis_task: str
    analysis_metrics: list[AnalysisMetric]
    analysis_filters: list[AnalysisFilter]
    analysis_entities: list[str]
    analysis_dimensions: list[str]
    analysis_time_expression: str | None
    analysis_population: str | None


class BIAgentContext(TypedDict):
    user_id: int
    dashboard_id: int
    allowed_dataset_ids: list[int]
    dashboard_title: str
    user_question: str


class MetadataResolutionContext(TypedDict):
    user_id: int
    dashboard_id: int
    allowed_dataset_ids: list[int]
    dashboard_title: str
    user_question: str
    user_intent_objective: str
    data_sources: list[dict[str, Any]]
    combination: str
    combination_key: list[str]
    time_range: str | None
    time_grain: str | None
    order_by: list[str]
    data_shape: str
    data_grain: str
    x_axis: str | None
    y_axis: list[str]
    series: str | None
    time_comparison: str | None
    chart_title: str | None


class DataBuilderContext(TypedDict):
    user_id: int
    dashboard_id: int
    allowed_dataset_ids: list[int]
    dashboard_title: str
    user_question: str
    user_intent_objective: str
    data_sources: list[dict[str, Any]]
    combination: str
    combination_key: list[str]
    time_range: str | None
    time_grain: str | None
    order_by: list[str]
    data_shape: str
    data_grain: str
    x_axis: str | None
    y_axis: list[str]
    series: str | None
    time_comparison: str | None
    chart_title: str | None
    metadata_resolution: dict[str, Any]
    dataset_id: int
    dataset_name: str
    table_name: str
    schema_name: str | None
    column_names: list[str]
