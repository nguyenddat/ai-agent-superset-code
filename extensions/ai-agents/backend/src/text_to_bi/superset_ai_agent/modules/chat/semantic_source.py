"""Reads the governed business content the Semantic Layer extension publishes for consumers.

The agent calls the Semantic Layer's read-only consumer endpoints as the asking user, by forwarding that user's
session cookie, so it only ever sees approved metrics, glossary terms and expert rules on datasets the user may
access. Nothing here reads the Semantic Layer's tables directly.
"""

import os
from dataclasses import dataclass, field
from typing import Any

import requests

SEMANTIC_LAYER_API = "/extensions/text-to-bi/superset-semantic-layer/semantic-layer"
EXPERT_RULES_API = "/extensions/text-to-bi/superset-semantic-layer/expert-rules/expert-rules"
REQUEST_TIMEOUT_SECONDS = 20


class SemanticSourceError(RuntimeError):
    """The Semantic Layer could not be read; the message is safe to show to the user."""


@dataclass
class SemanticCatalog:
    """Approved business content, flattened into the shapes the agent prompts list."""

    glossary_terms: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    expert_rules: list[dict[str, Any]] = field(default_factory=list)

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


def flatten_catalog(catalog: dict[str, Any], glossary: dict[str, Any], rules: dict[str, Any]) -> SemanticCatalog:
    """Turn the three consumer payloads into compact lists keyed by the IDs the agent must answer with."""
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
            "exceptions": [f"{item['when']} → {item['outcome']}" for item in rule.get("exceptions", [])],
            "example_questions": [item["question"] for item in rule.get("examples", [])],
            "metric_ids": rule.get("metric_ids") or [],
            "glossary_term_ids": rule.get("glossary_term_ids") or [],
        }
        for rule in rules.get("rules", [])
    ]
    return SemanticCatalog(glossary_terms=terms, metrics=metrics, expert_rules=expert_rules)


def load_semantic_catalog(cookie_header: str) -> SemanticCatalog:
    return flatten_catalog(
        _get_json(f"{SEMANTIC_LAYER_API}/semantic-catalog", cookie_header),
        _get_json(f"{SEMANTIC_LAYER_API}/glossary/discovery", cookie_header),
        _get_json(f"{EXPERT_RULES_API}/discover", cookie_header),
    )
