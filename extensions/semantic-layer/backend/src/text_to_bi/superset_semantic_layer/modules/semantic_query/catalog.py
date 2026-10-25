"""Safe, expression-free semantic catalog serialization."""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .contracts import contract_is_approved_current
from .relationships import RelationshipEnd, relationship_is_approved_current

FILTER_OPERATORS = ["==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN"]


def build_semantic_catalog(
    datasets: Mapping[int, Any],
    metric_contracts: Iterable[Any],
    relationships: Iterable[tuple[Any, RelationshipEnd, RelationshipEnd]],
    can_access: Callable[[Any], bool],
    max_rows: int,
    metric_details: Callable[[int, int], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return approved current metadata only for datasets accessible to the caller.

    ``metric_details(dataset_id, metric_id)`` adds governed business context, such as the business definition and the
    glossary terms naming the metric, to each visible metric. It never receives a metric the caller may not see.
    """
    access: dict[int, bool] = {}

    def allowed(dataset: Any) -> bool:
        dataset_id = getattr(dataset, "id", None)
        if dataset_id not in access:
            access[dataset_id] = bool(can_access(dataset))
        return access[dataset_id]

    catalog: dict[int, dict[str, Any]] = {}
    for contract in metric_contracts:
        dataset = datasets.get(getattr(contract, "dataset_id", None))
        if dataset is None or not allowed(dataset):
            continue
        metric = next((item for item in getattr(dataset, "metrics", []) if item.id == contract.metric_id), None)
        if metric is None or not contract_is_approved_current(contract, dataset, metric):
            continue
        catalog.setdefault(dataset.id, {"id": dataset.id, "name": dataset.table_name, "metrics": [], "dimensions": []})[
            "metrics"
        ].append(
            {
                "metric_id": metric.id,
                "metric_name": metric.metric_name,
                "verbose_name": getattr(metric, "verbose_name", None),
                "description": getattr(metric, "description", None),
                "d3format": getattr(metric, "d3format", None),
                **(metric_details(dataset.id, metric.id) if metric_details else {}),
            }
        )

    visible_relationships = []
    for contract, source, target in relationships:
        if source.dataset.id not in datasets or target.dataset.id not in datasets:
            continue
        if not (allowed(source.dataset) and allowed(target.dataset)) or not relationship_is_approved_current(contract, source, target):
            continue
        for dataset in (source.dataset, target.dataset):
            catalog.setdefault(dataset.id, {"id": dataset.id, "name": dataset.table_name, "metrics": [], "dimensions": []})
        visible_relationships.append(
            {
                "id": contract.id,
                "from_dataset_id": contract.from_dataset_id,
                "from_column": contract.from_column,
                "to_dataset_id": contract.to_dataset_id,
                "to_column": contract.to_column,
                "cardinality": contract.cardinality,
                "executable": False,
            }
        )

    for dataset_id, item in catalog.items():
        dataset = datasets.get(dataset_id)
        if dataset is None:
            continue
        item["metrics"].sort(key=lambda metric: (metric["metric_name"], metric["metric_id"]))
        # The label and type let a consumer map what people say ("ngày", "tốc độ gió tối đa") onto a column.
        item["dimensions"] = [
            {
                "name": column.column_name,
                "label": getattr(column, "verbose_name", None),
                "type": getattr(column, "type", None),
                "temporal": bool(getattr(column, "is_dttm", False)),
                "groupby": bool(getattr(column, "groupby", False)),
                "filterable": bool(getattr(column, "filterable", False)),
            }
            for column in getattr(dataset, "columns", [])
            if getattr(column, "is_active", None) is True
            and not getattr(column, "expression", None)
            and (getattr(column, "groupby", None) is True or getattr(column, "filterable", None) is True)
        ]
    return {
        "datasets": [catalog[key] for key in sorted(catalog)],
        "relationships": sorted(visible_relationships, key=lambda item: item["id"]),
        "limits": {"max_rows": max_rows, "filter_operators": FILTER_OPERATORS, "joins_supported": False},
    }
