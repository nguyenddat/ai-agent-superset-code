import inspect
import sys
from types import ModuleType, SimpleNamespace

import pytest

from text_to_bi.superset_semantic_layer.modules.glossary import service
from text_to_bi.superset_semantic_layer.modules.glossary.service import (
    GlossaryConflictError,
    GlossaryValidationError,
    approve_revision,
    extract_glossary_update_payload,
    glossary_link_fingerprint,
    normalize_glossary_payload,
    revision_is_discoverable,
)


def test_normalize_payload_trims_casefolds_and_deduplicates_synonyms():
    payload = normalize_glossary_payload(
        {
            "canonical_name": "  Net Revenue ",
            "definition": " Revenue after returns. ",
            "synonyms": [" net sales ", "NET SALES", "revenue net"],
            "provenance": "manual",
            "links": [{"dataset_id": 7, "kind": "dataset"}],
        }
    )

    assert payload["canonical_name"] == "Net Revenue"
    assert payload["normalized_name"] == "net revenue"
    assert payload["synonyms"] == ["net sales", "revenue net"]


@pytest.mark.parametrize(
    "payload",
    [
        {"canonical_name": "", "definition": "x", "synonyms": [], "provenance": "manual", "links": []},
        {
            "canonical_name": "Revenue",
            "definition": "x",
            "synonyms": [" revenue "],
            "provenance": "manual",
            "links": [{"dataset_id": 7, "kind": "dataset"}],
        },
        {
            "canonical_name": "Revenue",
            "definition": "x",
            "synonyms": [],
            "provenance": "unknown",
            "links": [{"dataset_id": 7, "kind": "dataset"}],
        },
    ],
)
def test_normalize_payload_rejects_unsafe_or_invalid_values(payload):
    with pytest.raises(GlossaryValidationError):
        normalize_glossary_payload(payload)


def test_fingerprint_is_credential_free_and_stales_when_live_object_changes():
    dataset = SimpleNamespace(
        id=7,
        catalog="analytics",
        schema="public",
        table_name="daily_weather",
        sql=None,
        database=SimpleNamespace(id=2, database_name="warehouse", sqlalchemy_uri="postgresql://user:secret@host/db"),
        columns=[SimpleNamespace(column_name="temperature", is_active=True, expression=None)],
        metrics=[SimpleNamespace(id=19, metric_name="avg_temperature", expression="AVG(temperature)")],
    )
    fingerprint = glossary_link_fingerprint(dataset, "metric", dataset.metrics[0])

    assert "secret" not in fingerprint
    dataset.metrics[0].expression = "AVG(temperature_f)"
    assert glossary_link_fingerprint(dataset, "metric", dataset.metrics[0]) != fingerprint


def test_validated_links_populates_only_the_matching_target_field():
    column = SimpleNamespace(id=86, column_name="quan_sat_id", is_active=True, expression=None)
    metric = SimpleNamespace(id=19, metric_name="observation_count", expression="COUNT(*)")
    dataset = SimpleNamespace(id=11, columns=[column], metrics=[metric])

    links = service._validated_links(
        SimpleNamespace(),
        [
            {"kind": "column", "dataset_id": 11, "column_name": "quan_sat_id"},
            {"kind": "metric", "dataset_id": 11, "metric_id": 19},
        ],
        lambda dataset_id: dataset if dataset_id == 11 else None,
    )

    assert links[0]["column_name"] == "quan_sat_id"
    assert links[0]["metric_id"] is None
    assert links[1]["column_name"] is None
    assert links[1]["metric_id"] == 19


@pytest.mark.parametrize(
    "link",
    [
        {"kind": "column", "dataset_id": 11, "column_name": "missing"},
        {"kind": "metric", "dataset_id": 11, "metric_id": 999},
    ],
)
def test_validated_links_rejects_missing_live_targets(link):
    dataset = SimpleNamespace(
        id=11,
        columns=[SimpleNamespace(id=86, column_name="quan_sat_id", is_active=True, expression=None)],
        metrics=[SimpleNamespace(id=19, metric_name="observation_count", expression="COUNT(*)")],
    )

    with pytest.raises(GlossaryValidationError, match="Invalid glossary link"):
        service._validated_links(SimpleNamespace(), [link], lambda _: dataset)


def test_only_approved_current_live_revision_is_discoverable():
    revision = SimpleNamespace(status="approved", is_current=True)
    link = SimpleNamespace(fingerprint="expected")

    assert revision_is_discoverable(revision, [link], lambda _: "expected")
    revision.status = "draft"
    assert not revision_is_discoverable(revision, [link], lambda _: "expected")
    revision.status = "approved"
    link.fingerprint = "stale"
    assert not revision_is_discoverable(revision, [link], lambda _: "expected")


def test_update_payload_extracts_transport_revision_before_normalization():
    payload = {
        "canonical_name": "Revenue",
        "definition": "Recognized revenue.",
        "synonyms": [],
        "provenance": "manual",
        "owner_id": None,
        "steward_id": None,
        "links": [{"dataset_id": 7, "kind": "dataset"}],
        "expected_revision": 4,
    }

    content, expected_revision = extract_glossary_update_payload(payload)

    assert expected_revision == 4
    assert "expected_revision" not in content
    assert normalize_glossary_payload(content)["owner_id"] is None
    assert normalize_glossary_payload(content)["steward_id"] is None


@pytest.mark.parametrize(
    "source_reference",
    ["prompt with spaces", "https://example.test/source?token=secret", "user:secret@host", ""],
)
def test_normalize_payload_rejects_unsafe_source_references(source_reference):
    with pytest.raises(GlossaryValidationError):
        normalize_glossary_payload(
            {
                "canonical_name": "Revenue",
                "definition": "Recognized revenue.",
                "synonyms": [],
                "provenance": "manual",
                "source_reference": source_reference,
                "links": [{"dataset_id": 7, "kind": "dataset"}],
            }
        )


def test_normalize_payload_accepts_hash_only_provenance():
    payload = normalize_glossary_payload(
        {
            "canonical_name": "Revenue",
            "definition": "Recognized revenue.",
            "synonyms": [],
            "provenance": "import",
            "source_hash": "a" * 64,
            "links": [{"dataset_id": 7, "kind": "dataset"}],
        }
    )

    assert payload["source_hash"] == "a" * 64
    assert "source_reference" not in payload


@pytest.mark.parametrize("source_hash", ["a" * 63, "g" * 64, 42])
def test_normalize_payload_requires_exact_hex_source_hash(source_hash):
    with pytest.raises(GlossaryValidationError):
        normalize_glossary_payload(
            {
                "canonical_name": "Revenue",
                "definition": "Recognized revenue.",
                "synonyms": [],
                "provenance": "manual",
                "source_hash": source_hash,
                "links": [{"dataset_id": 7, "kind": "dataset"}],
            }
        )


def test_lifecycle_mutations_request_current_revision_row_lock():
    source = inspect.getsource(service)

    assert "with_for_update()" in source
    for function in (service.update_draft, service.approve_revision, service.revoke_revision):
        assert "_lock_current_revision" in inspect.getsource(function)


def test_approval_rejects_stale_revision_after_locked_reread(monkeypatch):
    locked_current = SimpleNamespace(revision_number=3, status="draft", is_current=True)
    monkeypatch.setattr(service, "_lock_current_revision", lambda *_: locked_current)
    models = ModuleType("text_to_bi.superset_semantic_layer.models.glossary_term")
    models.GlossaryTermAuditEvent = SimpleNamespace
    monkeypatch.setitem(sys.modules, models.__name__, models)

    with pytest.raises(GlossaryConflictError):
        approve_revision(SimpleNamespace(), SimpleNamespace(), expected_revision=2, actor_id=1)
