"""Reads the governed business content the Semantic Layer extension publishes for consumers, and runs its metrics.

The agent calls the Semantic Layer's consumer endpoints as the asking user, by forwarding that user's session cookie
(and, to run a metric, their CSRF token), so it only ever sees and runs approved metrics, glossary terms and expert
rules on datasets the user may access. Nothing here reads the Semantic Layer's tables or the warehouse directly.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import requests

SEMANTIC_LAYER_API = "/extensions/text-to-bi/superset-semantic-layer/semantic-layer"
EXPERT_RULES_API = "/extensions/text-to-bi/superset-semantic-layer/expert-rules/expert-rules"
REQUEST_TIMEOUT_SECONDS = 20
# Approved content changes rarely; a user's follow-up questions reuse what was read a moment ago.
CATALOG_CACHE_SECONDS = 60

# Expert rule operators and the metric query operators they become; a rule using any other one cannot be run.
RULE_OPERATORS = {
    "equals": "==",
    "not_equals": "!=",
    "greater_than": ">",
    "greater_than_or_equal": ">=",
    "less_than": "<",
    "less_than_or_equal": "<=",
    "in": "IN",
    "not_in": "NOT IN",
}


class SemanticSourceError(RuntimeError):
    """The Semantic Layer could not be read; the message is safe to show to the user."""


class MetricQueryError(RuntimeError):
    """The Semantic Layer refused or failed a metric query; the message is safe to show to the user."""


@dataclass
class SemanticCatalog:
    """Approved business content, flattened into the shapes the agent prompts list."""

    glossary_terms: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    expert_rules: list[dict[str, Any]] = field(default_factory=list)
    # Each dataset with approved metrics: its columns, and the labelled values of its key columns.
    datasets: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "glossary_terms": [term["name"] for term in self.glossary_terms],
            "metrics": [metric["name"] for metric in self.metrics],
            "expert_rules": [rule["name"] for rule in self.expert_rules],
        }


def internal_superset_url() -> str:
    """Superset as seen from inside its own container; the Compose service listens on 8088."""
    return os.getenv("TEXT_TO_BI_SUPERSET_INTERNAL_URL", "http://127.0.0.1:8088").rstrip("/")


def _get_json(path: str, cookie_header: str) -> dict[str, Any]:
    try:
        response = requests.get(
            internal_superset_url() + path,
            headers={"Cookie": cookie_header, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as ex:
        raise SemanticSourceError("Không kết nối được tới Semantic Layer.") from ex
    if response.status_code in (401, 403):
        raise SemanticSourceError("Bạn chưa có quyền đọc dữ liệu quản trị nghiệp vụ của Semantic Layer.")
    if response.status_code != 200:
        raise SemanticSourceError(f"Semantic Layer trả về lỗi {response.status_code}.")
    return response.json()


def _condition_text(condition: dict[str, Any], column_names: dict[str, str]) -> str:
    column_id = str(condition.get("field_ref", {}).get("column_dictionary_id"))
    return f"{column_names.get(column_id, column_id)} {condition.get('operator')} {condition.get('value')}"


def rule_filters(rule: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The rule's conditions as metric query filters, or None when one of them cannot be expressed as a filter."""
    columns = rule.get("condition_columns") or {}
    filters = []
    for condition in rule.get("conditions", []):
        column = columns.get(str(condition.get("field_ref", {}).get("column_dictionary_id")))
        operator = RULE_OPERATORS.get(condition.get("operator"))
        if not column or not operator:
            return None
        filters.append({"column": column, "operator": operator, "value": condition.get("value")})
    return filters


def _dataset_entry(dataset: dict[str, Any], members: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": dataset["id"],
        "name": dataset.get("name"),
        "columns": [
            {
                key: column.get(key)
                for key in ("name", "label", "type", "temporal", "groupby", "filterable")
                if column.get(key) not in (None, "")
            }
            for column in dataset.get("dimensions", [])
        ],
        "labelled_values": [
            {
                "column": item["key_column"],
                "label": item.get("label"),
                "values": [{"value": member["value"], "label": member["label"]} for member in item.get("members", [])],
            }
            for item in members.get("dimensions", [])
        ],
    }


def flatten_catalog(
    catalog: dict[str, Any],
    glossary: dict[str, Any],
    rules: dict[str, Any],
    members_by_dataset: dict[int, dict[str, Any]] | None = None,
) -> SemanticCatalog:
    """Turn the consumer payloads into compact lists keyed by the IDs the agent must answer with."""
    terms = [
        {
            "id": term["term_id"],
            "name": term["canonical_name"],
            "synonyms": term.get("synonyms") or [],
            "definition": term.get("definition"),
        }
        for term in glossary.get("terms", [])
    ]
    metrics = [
        {
            "dataset_id": dataset["id"],
            "dataset_name": dataset.get("name"),
            "metric_id": metric["metric_id"],
            "name": metric.get("verbose_name") or metric["metric_name"],
            "metric_name": metric["metric_name"],
            "definition": metric.get("business_definition") or metric.get("description"),
            "unit": metric.get("unit"),
            "d3format": metric.get("d3format"),
            "glossary_term_ids": [term["term_id"] for term in metric.get("glossary_terms") or []],
        }
        for dataset in catalog.get("datasets", [])
        for metric in dataset.get("metrics", [])
    ]
    expert_rules = [
        {
            "id": rule["id"],
            "name": rule["name"],
            "dataset_id": rule.get("dataset_id"),
            "conditions": [
                _condition_text(condition, rule.get("column_names") or {}) for condition in rule.get("conditions", [])
            ],
            "filters": rule_filters(rule),
            "exceptions": [f"{item['when']} → {item['outcome']}" for item in rule.get("exceptions", [])],
            "example_questions": [item["question"] for item in rule.get("examples", [])],
            "metric_ids": rule.get("metric_ids") or [],
            "glossary_term_ids": rule.get("glossary_term_ids") or [],
        }
        for rule in rules.get("rules", [])
    ]
    datasets = [
        _dataset_entry(dataset, (members_by_dataset or {}).get(dataset["id"], {}))
        for dataset in catalog.get("datasets", [])
        if dataset.get("metrics")
    ]
    return SemanticCatalog(glossary_terms=terms, metrics=metrics, expert_rules=expert_rules, datasets=datasets)


def _members(dataset_id: int, cookie_header: str) -> dict[str, Any]:
    """Labelled key values help the agent filter by a name; without them it can still answer, so a failure is empty."""
    try:
        return _get_json(f"{SEMANTIC_LAYER_API}/dataset/{dataset_id}/dimension-members", cookie_header)
    except SemanticSourceError:
        return {}


def load_semantic_catalog(cookie_header: str) -> SemanticCatalog:
    """Read the three consumer payloads at once, then the labelled values of every dataset with approved metrics."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        catalog, glossary, rules = pool.map(
            lambda path: _get_json(path, cookie_header),
            (
                f"{SEMANTIC_LAYER_API}/semantic-catalog",
                f"{SEMANTIC_LAYER_API}/glossary/discovery",
                f"{EXPERT_RULES_API}/discover",
            ),
        )
        dataset_ids = [dataset["id"] for dataset in catalog.get("datasets", []) if dataset.get("metrics")]
        members = dict(zip(dataset_ids, pool.map(lambda dataset_id: _members(dataset_id, cookie_header), dataset_ids)))
    return flatten_catalog(catalog, glossary, rules, members)


_cache_lock = threading.Lock()
_cached_catalogs: dict[int, tuple[float, SemanticCatalog]] = {}


def cached_semantic_catalog(user_id: int, cookie_header: str) -> SemanticCatalog:
    """The user's catalog, read again after `CATALOG_CACHE_SECONDS`; it is per user because access differs."""
    now = time.monotonic()
    with _cache_lock:
        cached = _cached_catalogs.get(user_id)
    if cached and now - cached[0] < CATALOG_CACHE_SECONDS:
        return cached[1]
    catalog = load_semantic_catalog(cookie_header)
    with _cache_lock:
        _cached_catalogs[user_id] = (now, catalog)
    return catalog


def run_metric_query(
    dataset_id: int, metric_id: int, query: dict[str, Any], cookie_header: str, csrf_token: str,
) -> dict[str, Any]:
    """Run one approved metric through the Semantic Layer's governed execution endpoint, as the asking user."""
    path = f"{SEMANTIC_LAYER_API}/dataset/{dataset_id}/metrics/{metric_id}/semantic-query/execute"
    try:
        response = requests.post(
            internal_superset_url() + path,
            json=query,
            headers={"Cookie": cookie_header, "X-CSRFToken": csrf_token, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as ex:
        raise MetricQueryError("Không kết nối được tới Semantic Layer để chạy truy vấn.") from ex
    body = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
    if response.status_code != 200:
        message = body.get("message") if isinstance(body.get("message"), str) else None
        raise MetricQueryError(message or f"Semantic Layer trả về lỗi {response.status_code} khi chạy truy vấn.")
    return body
