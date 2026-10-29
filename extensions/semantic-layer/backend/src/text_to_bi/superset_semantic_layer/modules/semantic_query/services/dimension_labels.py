from typing import Any

from ...data_dictionary.dependencies import column_dictionary_repository


def label_dimensions(catalog_datasets: list[dict[str, Any]]) -> None:
    """A dimension without a Superset label takes its data dictionary name, so consumers can show "Ngày"."""
    dataset_ids = [dataset["id"] for dataset in catalog_datasets]
    if not dataset_ids:
        return
    names = {
        (entry.dataset_id, entry.column_name): entry.display_name
        for entry in column_dictionary_repository().list_for_datasets(dataset_ids)
    }
    for dataset in catalog_datasets:
        for dimension in dataset["dimensions"]:
            dimension["label"] = dimension.get("label") or names.get((dataset["id"], dimension["name"]))
