from typing import Any

from .client import SEMANTIC_LAYER_API, post_json


def catalog_metric(metric: dict[str, Any], dataset_name: str | None, provisional: bool) -> dict[str, Any]:
    """A metric the Semantic Layer returned, in the shape of an approved catalog metric."""
    return {
        "dataset_id": metric["dataset_id"],
        "dataset_name": dataset_name,
        "metric_id": metric["metric_id"],
        "name": metric.get("verbose_name") or metric["metric_name"],
        "metric_name": metric["metric_name"],
        "definition": metric.get("business_definition"),
        "unit": metric.get("unit"),
        "d3format": metric.get("d3format"),
        "glossary_term_ids": [],
        "provisional": provisional,
    }


def create_agent_metric(draft: dict[str, Any], cookie_header: str, csrf_token: str) -> tuple[dict[str, Any], bool]:
    """Save the metric the agent built on an aggregate dataset; returns it and whether it is still provisional."""
    answer = post_json(f"{SEMANTIC_LAYER_API}/agent-metrics", draft, cookie_header, csrf_token, "tạo metric")
    return answer["metric"], bool(answer.get("provisional"))


def run_metric_query(
    dataset_id: int, metric_id: int, query: dict[str, Any], cookie_header: str, csrf_token: str,
) -> dict[str, Any]:
    """Run one approved metric through the Semantic Layer's governed execution endpoint, as the asking user."""
    path = f"{SEMANTIC_LAYER_API}/dataset/{dataset_id}/metrics/{metric_id}/semantic-query/execute"
    return post_json(path, query, cookie_header, csrf_token, "chạy truy vấn")
