from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .catalog import dataset_entry, dimension_members
from .client import SEMANTIC_LAYER_API, cached, get_json, post_json


@dataclass
class DataModelSources:
    """What the data model offers when no approved metric answers: aggregate datasets to build a metric on, with the
    formulas already saved there, and base datasets to draft a dataset over."""

    aggregates: list[dict[str, Any]] = field(default_factory=list)
    bases: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "aggregate_datasets": [dataset.get("label") or dataset["name"] for dataset in self.aggregates],
            "base_datasets": [dataset.get("label") or dataset["name"] for dataset in self.bases],
        }


def _source_entry(dataset: dict[str, Any], members: dict[str, Any]) -> dict[str, Any]:
    """An aggregate or base dataset, shaped like a catalog dataset so the query planner can use it as one."""
    entry = {
        **dataset_entry({"id": dataset["id"], "name": dataset.get("name"), "dimensions": []}, members),
        "columns": dataset.get("columns", []),
    }
    for key in ("label", "description", "grain", "metrics"):
        if dataset.get(key):
            entry[key] = dataset[key]
    return entry


def load_data_model_sources(cookie_header: str) -> DataModelSources:
    """The aggregate and base datasets the user may query, with the labelled values and date ranges of aggregates."""
    payload = get_json(f"{SEMANTIC_LAYER_API}/agent-sources", cookie_header)
    datasets = payload.get("datasets", [])
    aggregates = [dataset for dataset in datasets if dataset.get("dataset_type") == "aggregate"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        members = list(pool.map(lambda dataset: dimension_members(dataset["id"], cookie_header), aggregates))
    return DataModelSources(
        aggregates=[_source_entry(dataset, found) for dataset, found in zip(aggregates, members)],
        bases=[_source_entry(dataset, {}) for dataset in datasets if dataset.get("dataset_type") == "base"],
    )


_cached_sources: dict[int, tuple[float, DataModelSources]] = {}


def cached_data_model_sources(user_id: int, cookie_header: str) -> DataModelSources:
    return cached(_cached_sources, user_id, lambda: load_data_model_sources(cookie_header))


_cached_schema_graphs: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}


def cached_schema_graph(user_id: int, database_id: int, cookie_header: str) -> dict[str, Any]:
    """The base tables of one database the user may read in full, and the approved relationships between them."""
    path = f"{SEMANTIC_LAYER_API}/schema-graph?database_id={database_id}"
    return cached(_cached_schema_graphs, (user_id, database_id), lambda: get_json(path, cookie_header))


def propose_agent_dataset(draft: dict[str, Any], cookie_header: str, csrf_token: str) -> dict[str, Any]:
    """Keep the dataset the agent drafted over base datasets for an administrator; returns the proposal."""
    path = f"{SEMANTIC_LAYER_API}/agent-dataset-proposals"
    return post_json(path, draft, cookie_header, csrf_token, "gửi đề xuất dataset")["proposal"]
