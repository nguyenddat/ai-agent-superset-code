from typing import Any

from superset.connectors.sqla.models import SqlaTable

from ....core.security import can_access_dataset
from ...semantic_query.services.contracts import contract_is_approved_current
from ...semantic_query.services.metric_review import metric_contract_for
from ...superset.services.datasets import get_dataset
from ..dependencies import glossary_term_link_repository, glossary_term_revision_repository
from ..models import GlossaryTermLink
from .glossary import glossary_link_fingerprint


def glossary_links(revision_id: int) -> list[GlossaryTermLink]:
    return glossary_term_link_repository().for_revision(revision_id)


def glossary_link_target(link: GlossaryTermLink, dataset: SqlaTable) -> Any | None:
    if link.kind == "dataset":
        return None
    if link.kind == "column":
        return next((column for column in dataset.columns if column.column_name == link.column_name), None)
    return next((metric for metric in dataset.metrics if metric.id == link.metric_id), None)


def glossary_metric_approved(dataset: SqlaTable, metric: Any) -> bool:
    """A term builds on a metric only while the metric's contract is approved for its current formula."""
    return contract_is_approved_current(metric_contract_for(dataset.id, metric.id), dataset, metric)


def discoverable_glossary_terms() -> list[dict[str, Any]]:
    """Approved current terms with only their fresh links to datasets the caller may access."""
    rows = glossary_term_revision_repository().approved_current()
    terms = []
    for revision in rows:
        visible_links = []
        for link in glossary_links(revision.id):
            dataset = get_dataset(link.dataset_id)
            if dataset is None or not can_access_dataset(dataset):
                continue
            target = glossary_link_target(link, dataset)
            if link.kind != "dataset" and target is None:
                continue
            if glossary_link_fingerprint(dataset, link.kind, target) != link.fingerprint:
                continue
            if link.kind == "metric" and not glossary_metric_approved(dataset, target):
                continue
            visible_links.append(
                {
                    "kind": link.kind,
                    "dataset_id": link.dataset_id,
                    "column_name": link.column_name,
                    "metric_id": link.metric_id,
                }
            )
        if not visible_links:
            continue
        terms.append(
            {
                "term_id": revision.term_id,
                "canonical_name": revision.term.canonical_name,
                "definition": revision.definition,
                "synonyms": revision.synonyms or [],
                "links": visible_links,
            }
        )
    return terms
