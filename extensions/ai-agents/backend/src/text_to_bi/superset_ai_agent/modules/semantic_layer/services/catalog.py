from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from ..exceptions import SemanticLayerUnavailableError
from .client import EXPERT_RULES_API, SEMANTIC_LAYER_API, cached, get_json

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


def dataset_entry(dataset: dict[str, Any], members: dict[str, Any]) -> dict[str, Any]:
    """A dataset as the query planner reads it: columns, labelled key values and the date range of the data."""
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
        # The first and last date of each date column, so a question outside them is known to have no data.
        "time_ranges": members.get("time_ranges", []),
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
        dataset_entry(dataset, (members_by_dataset or {}).get(dataset["id"], {}))
        for dataset in catalog.get("datasets", [])
        if dataset.get("metrics")
    ]
    return SemanticCatalog(glossary_terms=terms, metrics=metrics, expert_rules=expert_rules, datasets=datasets)


def dimension_members(dataset_id: int, cookie_header: str) -> dict[str, Any]:
    """Labelled key values help the agent filter by a name; without them it can still answer, so a failure is empty."""
    try:
        return get_json(f"{SEMANTIC_LAYER_API}/dataset/{dataset_id}/dimension-members", cookie_header)
    except SemanticLayerUnavailableError:
        return {}


def load_semantic_catalog(cookie_header: str) -> SemanticCatalog:
    """Read the three consumer payloads at once, then the labelled values of every dataset with approved metrics."""
    paths = (
        f"{SEMANTIC_LAYER_API}/semantic-catalog",
        f"{SEMANTIC_LAYER_API}/glossary/discovery",
        f"{EXPERT_RULES_API}/discover",
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        catalog, glossary, rules = pool.map(lambda path: get_json(path, cookie_header), paths)
        dataset_ids = [dataset["id"] for dataset in catalog.get("datasets", []) if dataset.get("metrics")]
        found = pool.map(lambda dataset_id: dimension_members(dataset_id, cookie_header), dataset_ids)
        members = dict(zip(dataset_ids, found))
    return flatten_catalog(catalog, glossary, rules, members)


_cached_catalogs: dict[int, tuple[float, SemanticCatalog]] = {}


def cached_semantic_catalog(user_id: int, cookie_header: str) -> SemanticCatalog:
    return cached(_cached_catalogs, user_id, lambda: load_semantic_catalog(cookie_header))
