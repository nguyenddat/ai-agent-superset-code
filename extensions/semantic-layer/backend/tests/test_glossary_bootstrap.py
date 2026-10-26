"""Regression tests for glossary safety and isolated table bootstrap behavior."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from text_to_bi.superset_semantic_layer.modules.glossary import service


def _payload(**overrides):
    return {
        "canonical_name": "Revenue",
        "definition": "Recognized revenue.",
        "synonyms": [],
        "provenance": "manual",
        "links": [{"dataset_id": 7, "kind": "dataset"}],
        **overrides,
    }


def test_raw_secret_like_source_reference_is_rejected():
    with pytest.raises(service.GlossaryValidationError, match="Unsupported glossary fields"):
        service.normalize_glossary_payload(_payload(source_reference="postgresql://admin:secret@db/internal"))


def test_duplicate_canonical_name_flush_rolls_back_and_raises_conflict(monkeypatch):
    class GlossaryTerm:
        def __init__(self, **values):
            self.__dict__.update(values)

    models = ModuleType("text_to_bi.superset_semantic_layer.models.glossary_term")
    models.GlossaryTerm = GlossaryTerm
    models.GlossaryTermAuditEvent = SimpleNamespace
    models.GlossaryTermLink = SimpleNamespace
    models.GlossaryTermRevision = SimpleNamespace
    monkeypatch.setitem(sys.modules, models.__name__, models)

    class Session:
        def __init__(self):
            self.rolled_back = False

        def query(self, _model):
            return SimpleNamespace(filter_by=lambda **_values: SimpleNamespace(one_or_none=lambda: None))

        def add(self, _record):
            pass

        def flush(self):
            raise IntegrityError("insert", {}, Exception("duplicate normalized name"))

        def rollback(self):
            self.rolled_back = True

    session = Session()
    with pytest.raises(service.GlossaryConflictError, match="canonical name"):
        service.create_draft(session, _payload(), 1, lambda _dataset_id: None, lambda _user_id: True)
    assert session.rolled_back


def test_glossary_bootstrap_creates_parent_tables_before_children_with_checkfirst():
    route_path = Path(__file__).parents[1] / "src/text_to_bi/superset_semantic_layer/modules/catalog/route.py"
    module = ast.parse(route_path.read_text(encoding="utf-8"))
    migration = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_migrate_dictionary_tables")
    namespace = _migration_namespace()
    exec(compile(ast.Module(body=[migration], type_ignores=[]), str(route_path), "exec"), namespace)  # noqa: S102

    namespace["_migrate_dictionary_tables"]()
    namespace["_migrate_dictionary_tables"]()

    glossary_calls = [call for call in namespace["calls"] if call[0].startswith("Glossary")]
    assert [name for name, _ in glossary_calls] == [
        "GlossaryTerm",
        "GlossaryTermRevision",
        "GlossaryTermLink",
        "GlossaryTermAuditEvent",
    ] * 2
    assert all(checkfirst for _, checkfirst in glossary_calls)


def test_expert_rule_bootstrap_creates_parent_tables_before_children_with_checkfirst():
    route_path = Path(__file__).parents[1] / "src/text_to_bi/superset_semantic_layer/modules/catalog/route.py"
    module = ast.parse(route_path.read_text(encoding="utf-8"))
    migration = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_migrate_dictionary_tables")
    namespace = _migration_namespace()
    exec(compile(ast.Module(body=[migration], type_ignores=[]), str(route_path), "exec"), namespace)  # noqa: S102

    namespace["_migrate_dictionary_tables"]()

    expert_calls = [call for call in namespace["calls"] if call[0].startswith("ExpertRule")]
    assert [name for name, _ in expert_calls] == [
        "ExpertRule",
        "ExpertRuleRevision",
        "ExpertRuleLink",
        "ExpertRuleAuditEvent",
    ]
    assert all(checkfirst for _, checkfirst in expert_calls)


def _migration_namespace():
    calls = []

    class Table:
        def __init__(self, name):
            self.name = name

        def create(self, *, bind, checkfirst):
            calls.append((self.name, checkfirst))

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return SimpleNamespace(scalars=list)

    engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"), begin=lambda: Connection())
    db = SimpleNamespace(engine=engine)
    inspect = lambda _engine: SimpleNamespace(
        get_columns=lambda _name: [],
        get_indexes=lambda _name: [],
        has_table=lambda _name: False,
    )
    names = (
        "DataLayer",
        "DatasetDictionary",
        "ColumnDictionary",
        "DatasetGrain",
        "BusinessDomain",
        "LineageEdge",
        "BusinessCanvas",
        "LineageCanvas",
        "MetricContract",
        "MetricContractEvent",
        "MetricDefinition",
        "RelationshipContract",
        "GlossaryTerm",
        "GlossaryTermRevision",
        "GlossaryTermLink",
        "GlossaryTermAuditEvent",
        "ExpertRule",
        "ExpertRuleRevision",
        "ExpertRuleLink",
        "ExpertRuleAuditEvent",
        "DatasetProposal",
    )
    namespace ={name: SimpleNamespace(__tablename__=name, __table__=Table(name)) for name in names}
    namespace.update(
        db=db,
        inspect=inspect,
        text=lambda value: value,
        business_domain_dataset=Table("business_domain_dataset"),
        calls=calls,
    )
    return namespace
