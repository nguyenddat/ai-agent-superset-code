"""Turns a user's own definition of a qualitative concept into conditions on a dataset, once, when they confirm it.

A definition is the user's words ("tốc độ gió tối đa trong ngày từ 45 km/h"). Read again by the model at every
question, the same words could become a different threshold; stored as checked conditions, they are added to every
later query as they are, like an approved expert rule's. A definition no filter can express keeps no conditions, and
the agent goes on reading its words.
"""

import json
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from pydantic import BaseModel, Field

from ...core.chat_models import get_chat_model
from ..chat import prompts
from ..chat.query import QueryPlanError, checked_conditions
from ..chat.semantic_source import SemanticCatalog, cached_semantic_catalog

logger = logging.getLogger(__name__)


class ConditionFilter(BaseModel):
    column: str
    operator: Literal["==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN"]
    value: int | float | str | list[int | float | str]


class DefinitionConditions(BaseModel):
    dataset_id: int | None = None
    filters: list[ConditionFilter] = Field(default_factory=list)
    reason: str = ""


def _catalog_block(catalog: SemanticCatalog) -> str:
    content = {
        "metrics": [
            {key: metric.get(key) for key in ("dataset_id", "name", "definition", "unit")} for metric in catalog.metrics
        ],
        "datasets": [
            {key: dataset.get(key) for key in ("id", "name", "columns", "labelled_values")}
            for dataset in catalog.datasets
        ],
    }
    return f"Dataset và metric:\n```json\n{json.dumps(content, ensure_ascii=False, default=str)}\n```"


def structured_conditions(definition: dict[str, Any], catalog: SemanticCatalog, model: Any) -> dict[str, Any] | None:
    """`{dataset_id, filters}` for a qualitative concept's definition, or None when it is not a set of conditions."""
    if definition["kind"] != "expert_rule" or not catalog.datasets:
        return None
    asked = {key: definition.get(key) for key in ("name", "concept", "definition")}
    content = f"Cách hiểu:\n```json\n{json.dumps(asked, ensure_ascii=False)}\n```\n\n{_catalog_block(catalog)}"
    try:
        answer = model.with_structured_output(DefinitionConditions).invoke(
            [("system", prompts.STRUCTURE_DEFINITION), ("human", content)],
        )
    except Exception:
        logger.exception("Could not structure the definition %s", definition.get("name"))
        return None
    dataset = next((item for item in catalog.datasets if item["id"] == answer.dataset_id), None)
    if dataset is None or not answer.filters:
        return None
    try:
        filters = checked_conditions(dataset, [item.model_dump() for item in answer.filters])
    except QueryPlanError:
        return None
    return {"dataset_id": dataset["id"], "filters": filters}


def structure_definitions(
    definitions: Sequence[dict[str, Any]], load_catalog: Callable[[], SemanticCatalog], model: Any,
) -> list[dict[str, Any] | None]:
    """The conditions of each definition, worked out side by side; the catalog is read only when one needs it."""
    if not any(item["kind"] == "expert_rule" for item in definitions):
        return [None] * len(definitions)
    try:
        catalog = load_catalog()
    except Exception:
        logger.exception("Could not read the semantic catalog to structure definitions")
        return [None] * len(definitions)
    with ThreadPoolExecutor(max_workers=max(1, len(definitions))) as pool:
        return list(pool.map(lambda item: structured_conditions(item, catalog, model), definitions))


def conditions_for(
    definitions: Sequence[dict[str, Any]], user_id: int, cookie_header: str,
) -> list[dict[str, Any] | None]:
    """Conditions for definitions a user is saving, read against the catalog that user may see."""
    try:
        model = get_chat_model()
    except RuntimeError:
        logger.exception("No chat model to structure definitions")
        return [None] * len(definitions)
    return structure_definitions(definitions, lambda: cached_semantic_catalog(user_id, cookie_header), model)
