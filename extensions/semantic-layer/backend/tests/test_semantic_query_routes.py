"""Isolated behavioural coverage for the security-critical route bodies.

Superset itself is intentionally not installed in the local extension toolchain.
The harness compiles relevant methods from ``route.py`` with small fakes, so
these tests exercise the real handler source without a Superset runtime.
"""

import ast
import sys
import types
from datetime import UTC, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from text_to_bi.superset_semantic_layer.modules.semantic_query.compiler import (
    SemanticQueryError,
    compile_semantic_query,
)
from text_to_bi.superset_semantic_layer.modules.semantic_query.contracts import (
    METRIC_CONTRACT_RULE,
    build_metric_chart_payload,
    contract_is_approved_current,
    metric_contract_hash,
    metric_contract_ineligibility,
    metric_contract_state,
    metric_is_eligible_for_contract,
    parse_contract_metric,
)
from text_to_bi.superset_semantic_layer.modules.semantic_query.relationships import (
    RelationshipEnd,
    relationship_cardinality,
    relationship_contract_hash,
)

ROUTE_PATH = Path(__file__).parents[1] / "src" / "text_to_bi" / "superset_semantic_layer" / "modules" / "catalog" / "route.py"


class _ResponseAPI:
    def response(self, status, **payload):
        return status, payload

    def response_400(self, **payload):
        return self.response(400, **payload)

    def response_500(self, **payload):
        return self.response(500, **payload)


class _Session:
    def __init__(self, datasets):
        self.datasets, self.commits, self.rollbacks, self.added = datasets, 0, 0, []

    def get(self, model, identifier):
        return self.datasets.get(identifier)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _ModelField:
    def __eq__(self, value):
        return value

    def in_(self, values):
        return values


class _MetricContract:
    status = dataset_id = _ModelField()

    def __init__(self, dataset_id, metric_id, owner_id=None):
        self.id, self.dataset_id, self.metric_id, self.owner_id = 91, dataset_id, metric_id, owner_id
        self.approver_id = self.revoker_id = self.approved_at = self.revoked_at = None


class _RelationshipContract:
    status = _ModelField()
    next_id = 101

    def __init__(self, **values):
        self.id = self.next_id
        type(self).next_id += 1
        self.owner_id = self.approver_id = self.revoker_id = self.approved_at = self.revoked_at = None
        for key, value in values.items():
            setattr(self, key, value)


class _CatalogDataset:
    id = database_id = table_name = _ModelField()


def _dataset():
    column = SimpleNamespace(column_name="temperature", is_active=True, groupby=True, filterable=True, expression=None)
    metric = SimpleNamespace(id=4, metric_name="average_temperature", expression='AVG("temperature")')
    return SimpleNamespace(
        id=7, columns=[column], metrics=[metric], sql=None, catalog=None, schema=None, table_name="weather",
        database=SimpleNamespace(id=1, database_name="warehouse"),
    )


def _route_api(datasets):
    tree = ast.parse(ROUTE_PATH.read_text(encoding="utf-8"))
    wanted = {
        "_is_admin", "_can_preview_semantic_query", "_dataset_metric", "_serialize_metric_contract",
        "_serialize_relationship_contract", "create_metric_contract_candidate", "approve_metric_contract",
        "revoke_metric_contract", "execute_metric_contract", "create_relationship_contract_candidate",
        "approve_relationship_contract", "revoke_relationship_contract", "semantic_catalog", "_query_dataset",
        "list_metric_contracts",
    }
    class_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SemanticLayerAPI")
    class_node.decorator_list = []
    class_node.body = [node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    for node in class_node.body:
        node.decorator_list = [item for item in node.decorator_list if isinstance(item, ast.Name) and item.id == "staticmethod"]
    cap_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_semantic_query_row_cap")
    namespace = {
        "RestApi": _ResponseAPI, "staticmethod": staticmethod,
        "SqlaTable": _CatalogDataset, "ColumnDictionary": object, "Any": Any, "datetime": datetime, "timezone": timezone,
        "current_user": SimpleNamespace(is_authenticated=True, id=3, roles=[SimpleNamespace(name="Admin")]),
        "security_manager": SimpleNamespace(raise_for_access=lambda **_: None),
        "SupersetSecurityException": type("SupersetSecurityException", (Exception,), {}), "MetricContract": _MetricContract,
        "RelationshipContract": _RelationshipContract, "db": SimpleNamespace(session=_Session(datasets)),
        "request": SimpleNamespace(get_json=lambda silent=True: {"dimensions": [], "filters": []}, args=SimpleNamespace(get=lambda *_args, **_kwargs: None)),
        "current_app": SimpleNamespace(config={}), "_ensure_dictionary_tables": lambda: None,
        "metric_is_eligible_for_contract": metric_is_eligible_for_contract, "metric_contract_hash": metric_contract_hash,
        "metric_contract_ineligibility": metric_contract_ineligibility, "metric_contract_state": metric_contract_state,
        "parse_contract_metric": parse_contract_metric,
        "contract_is_approved_current": contract_is_approved_current, "execute_approved_chart_query": None,
        "relationship_cardinality": relationship_cardinality, "relationship_contract_hash": relationship_contract_hash,
        "relationship_is_approved_current": lambda contract, *_: contract.status == "approved",
        "RelationshipEnd": RelationshipEnd, "build_semantic_catalog": None,
        "_is_superset_access_error": lambda error: "access" in type(error).__name__.lower(),
        "logger": SimpleNamespace(exception=lambda *args, **kwargs: None), "SEMANTIC_QUERY_MAX_ROWS": 1000,
    }
    module = ast.Module(body=[cap_node, class_node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROUTE_PATH), "exec"), namespace)  # noqa: S102
    return namespace["SemanticLayerAPI"](), namespace


def _install_chartdata_stubs(monkeypatch):
    schemas = types.ModuleType("superset.charts.schemas")
    schemas.ChartDataQueryContextSchema = lambda: SimpleNamespace(load=lambda payload: payload)
    command = types.ModuleType("superset.commands.chart.data.get_data_command")
    command.ChartDataCommand = lambda payload: SimpleNamespace(validate=lambda: None, run=lambda: {"queries": [{}]})
    monkeypatch.setitem(sys.modules, "superset.charts.schemas", schemas)
    monkeypatch.setitem(sys.modules, "superset.commands.chart.data.get_data_command", command)


def test_candidate_requires_admin_and_redacts_contract_details():
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    api._contract_for = lambda *_: None
    status, payload = api.create_metric_contract_candidate(dataset.id, 4)
    assert status == 201 and payload["contract"]["status"] == "candidate"
    assert "expression" not in payload["contract"] and "expression_hash" not in payload["contract"]
    namespace["current_user"].roles = []
    assert api.create_metric_contract_candidate(dataset.id, 4)[0] == 403


def test_new_candidates_carry_their_hash_before_joining_the_session():
    """Hashing lazy-loads the dataset's database and autoflushes, so a contract must be complete when added."""
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    session = namespace["db"].session
    snapshots = []
    session.add = lambda item: snapshots.append(dict(vars(item)))
    api._contract_for = lambda *_: None
    assert api.create_metric_contract_candidate(dataset.id, 4)[0] == 201
    assert snapshots[0]["expression_hash"] == metric_contract_hash(dataset, dataset.metrics[0])
    assert snapshots[0]["owner_id"] == 3

    source, target = _relationship_context()
    api._relationship_contract_context = lambda *_: (source, target, None)
    api._relationship_contract_for = lambda *_: None
    assert api.create_relationship_contract_candidate(source.dataset.id, 23)[0] == 201
    assert snapshots[1]["contract_hash"] and snapshots[1]["to_dataset_id"] == target.dataset.id
    assert snapshots[1]["owner_id"] == 3


def test_metric_contract_approve_and_revoke_lifecycle():
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    holder = {}
    api._contract_for = lambda *_: holder.get("contract")
    assert api.create_metric_contract_candidate(dataset.id, 4)[0] == 201
    holder["contract"] = namespace["db"].session.added[0]
    assert api.approve_metric_contract(dataset.id, 4)[0] == 200
    assert holder["contract"].status == "approved"
    assert api.revoke_metric_contract(dataset.id, 4)[0] == 200
    assert holder["contract"].status == "revoked"


def test_csrf_wrapper_rejects_before_the_handler():
    source = ast.parse(ROUTE_PATH.read_text(encoding="utf-8"))
    node = next(item for item in source.body if isinstance(item, ast.FunctionDef) and item.name == "_csrf_protected")
    namespace = {"wraps": lambda method: lambda wrapper: wrapper, "request": SimpleNamespace(headers={}), "ValidationError": ValueError}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(ROUTE_PATH), "exec"), namespace)  # noqa: S102
    namespace["validate_csrf"] = lambda _: (_ for _ in ()).throw(ValueError())
    called = []
    wrapped = namespace["_csrf_protected"](lambda self: called.append(True))
    assert wrapped(SimpleNamespace(response=lambda status, **payload: (status, payload)))[0] == 403
    assert called == []


def test_execute_denial_security_error_and_truncation_are_mapped(monkeypatch):
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    metric, contract = dataset.metrics[0], _MetricContract(dataset.id, 4)
    contract.status, contract.expression_hash = "approved", metric_contract_hash(dataset, metric)
    api._contract_for = lambda *_: contract
    api._can_access_semantic_query_dataset = lambda _: False
    assert api.execute_metric_contract(dataset.id, metric.id)[0] == 403
    api._can_access_semantic_query_dataset = lambda _: True
    _install_chartdata_stubs(monkeypatch)
    namespace["execute_approved_chart_query"] = lambda *args: (_ for _ in ()).throw(type("AccessDenied", (Exception,), {})())
    assert api.execute_metric_contract(dataset.id, metric.id)[0] == 403
    namespace["current_app"].config["SEMANTIC_QUERY_MAX_ROWS"] = 10_000
    namespace["execute_approved_chart_query"] = lambda *args: {"colnames": ["city"], "data": [{"city": "A"}] * 1001}
    status, payload = api.execute_metric_contract(dataset.id, metric.id)
    assert status == 200 and payload["row_count"] == 1000 and payload["truncated"] is True


def test_execute_returns_the_superset_sql_to_administrators_only(monkeypatch):
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    metric, contract = dataset.metrics[0], _MetricContract(dataset.id, 4)
    contract.status, contract.expression_hash = "approved", metric_contract_hash(dataset, metric)
    api._contract_for = lambda *_: contract
    api._can_access_semantic_query_dataset = lambda _: True
    _install_chartdata_stubs(monkeypatch)
    executed_sql = "SELECT city, AVG(temperature) FROM weather WHERE tenant_id = 7 GROUP BY city"
    namespace["execute_approved_chart_query"] = lambda *args: {"colnames": ["city"], "data": [], "query": executed_sql}
    assert api.execute_metric_contract(dataset.id, metric.id)[1]["sql"] == executed_sql
    namespace["current_user"].roles = []
    assert api.execute_metric_contract(dataset.id, metric.id)[1]["sql"] is None


def test_preview_compiler_and_execute_payload_reject_joins():
    with pytest.raises(SemanticQueryError, match="joins are unsupported"):
        compile_semantic_query(
            {"name": "weather", "table": "weather", "dialect": "postgresql"},
            [{"name": "m", "dataset": "weather", "column": "temperature", "aggregation": "avg", "approved": True}],
            [], {"metric": "m", "joins": [{"dataset": "other"}]},
        )
    with pytest.raises(ValueError, match="joins are not supported"):
        build_metric_chart_payload(_dataset(), SimpleNamespace(metric_name="m"), {"joins": []}, 1000)


def _relationship_context():
    source_dataset = _dataset()
    target_column = SimpleNamespace(column_name="id", is_active=True, expression=None, type="INT")
    target_dataset = SimpleNamespace(
        id=8, columns=[target_column], sql=None, catalog=None, schema=None, table_name="stations",
        database=source_dataset.database,
    )
    source_entry = SimpleNamespace(column_name="station_id", is_fk=True, is_pk=False, is_unique=False, data_type="INT")
    target_entry = SimpleNamespace(column_name="id", is_fk=False, is_pk=True, is_unique=True, data_type="INT")
    source_dataset.columns.append(SimpleNamespace(column_name="station_id", is_active=True, expression=None, type="INT"))
    return RelationshipEnd(source_dataset, source_entry, 0), RelationshipEnd(target_dataset, target_entry, 1)


def test_relationship_handlers_cover_candidate_approval_and_audit_reset():
    source, target = _relationship_context()
    api, namespace = _route_api({source.dataset.id: source.dataset})
    holder = {}
    api._relationship_contract_context = lambda *_: (source, target, None)
    api._relationship_contract_for = lambda *_: holder.get("contract")
    namespace["RelationshipContract"] = _RelationshipContract
    assert api.create_relationship_contract_candidate(source.dataset.id, 23)[0] == 201
    contract = holder["contract"] = namespace["db"].session.added[0]
    assert api.approve_relationship_contract(source.dataset.id, 23)[0] == 200
    assert contract.status == "approved" and contract.approver_id == 3
    assert api.create_relationship_contract_candidate(source.dataset.id, 23)[0] == 409
    api._relationship_contract_context = lambda *_: (None, None, (400, {"message": "invalid relationship"}))
    assert api.create_relationship_contract_candidate(source.dataset.id, 23)[0] == 400
    api._relationship_contract_context = lambda *_: (source, target, None)
    contract.revoker_id, contract.revoked_at = 9, datetime.now(UTC)
    contract.status = "revoked"
    assert api.create_relationship_contract_candidate(source.dataset.id, 23)[0] == 201
    assert contract.status == "candidate"
    assert (contract.approver_id, contract.approved_at, contract.revoker_id, contract.revoked_at) == (None, None, None, None)
    contract.contract_hash = "changed"
    assert api.approve_relationship_contract(source.dataset.id, 23)[0] == 400
    namespace["current_user"].roles = []
    assert api.create_relationship_contract_candidate(source.dataset.id, 23)[0] == 403


def test_relationship_revoke_binds_explicit_contract_id_to_path_relationship():
    source, target = _relationship_context()
    api, namespace = _route_api({source.dataset.id: source.dataset})
    values = {"to_dataset_id": target.dataset.id, "to_column": target.entry.column_name, "cardinality": "many_to_one"}
    unrelated = _RelationshipContract(from_dataset_id=source.dataset.id, from_column="other", **values)
    stale = _RelationshipContract(from_dataset_id=source.dataset.id, from_column="station_id", **values)
    wrong_dataset = _RelationshipContract(from_dataset_id=target.dataset.id, from_column="station_id", **values)
    stale.status = unrelated.status = wrong_dataset.status = "approved"
    entry = SimpleNamespace(column_name="station_id")
    api._fk_entry = lambda dataset_id, column_id: entry if (dataset_id, column_id) == (source.dataset.id, 23) else None
    # Simulate a stale contract lookup: the caller supplies the immutable contract ID.
    api._relationship_contract_for = lambda *_: None
    api._relationship_ends = lambda *_: None
    contracts = {stale.id: stale, unrelated.id: unrelated, wrong_dataset.id: wrong_dataset}
    namespace["db"].session.get = lambda model, identifier: contracts.get(identifier)

    def revoke_with(contract_id):
        namespace["request"].args = SimpleNamespace(
            get=lambda *_args, **_kwargs: contract_id
        )
        return api.revoke_relationship_contract(source.dataset.id, 23)

    session = namespace["db"].session
    assert revoke_with(None)[0] == 404
    assert revoke_with(99999)[0] == 404
    assert revoke_with(unrelated.id)[0] == 404
    assert revoke_with(wrong_dataset.id)[0] == 404
    assert (unrelated.status, wrong_dataset.status, stale.status) == ("approved", "approved", "approved")
    assert session.commits == 0

    assert revoke_with(stale.id)[0] == 200
    assert stale.status == "revoked" and unrelated.status == wrong_dataset.status == "approved"
    assert session.commits == 1


def test_relationship_revoke_rejects_contract_id_when_path_entry_is_missing():
    source, target = _relationship_context()
    api, namespace = _route_api({source.dataset.id: source.dataset})
    contract = _RelationshipContract(
        from_dataset_id=source.dataset.id,
        from_column="station_id",
        to_dataset_id=target.dataset.id,
        to_column=target.entry.column_name,
        cardinality="many_to_one",
    )
    contract.status = "approved"
    api._fk_entry = lambda *_: None
    api._relationship_contract_for = lambda *_: None
    namespace["db"].session.get = lambda model, identifier: contract if identifier == contract.id else None
    namespace["request"].args = SimpleNamespace(get=lambda *_args, **_kwargs: contract.id)

    assert api.revoke_relationship_contract(source.dataset.id, 999)[0] == 404
    assert contract.status == "approved"
    assert namespace["db"].session.commits == 0


def test_semantic_catalog_hides_denied_dataset():
    dataset = _dataset()
    contract = _MetricContract(dataset.id, dataset.metrics[0].id)
    contract.status, contract.expression_hash = "approved", metric_contract_hash(dataset, dataset.metrics[0])
    api, namespace = _route_api({dataset.id: dataset})

    class Query:
        def __init__(self, model):
            self.model = model

        def filter(self, *_):
            return self

        def all(self):
            if self.model is _MetricContract:
                return [contract]
            if self.model is _CatalogDataset:
                return [dataset]
            return []

    namespace["db"].session.query = lambda model: Query(model)
    namespace["build_semantic_catalog"] = __import__(
        "text_to_bi.superset_semantic_layer.modules.semantic_query.catalog", fromlist=["build_semantic_catalog"]
    ).build_semantic_catalog
    api._can_access_semantic_query_dataset = lambda _: False
    status, payload = api.semantic_catalog()
    assert status == 200 and payload["datasets"] == [] and payload["relationships"] == []


def _metric_list_api(dataset, contracts):
    api, namespace = _route_api({dataset.id: dataset})

    class Query:
        def __init__(self, model):
            self.model = model

        def filter(self, *_):
            return self

        def order_by(self, *_):
            return self

        def all(self):
            return {_CatalogDataset: [dataset], _MetricContract: contracts}.get(self.model, [])

    namespace["db"].session.query = Query
    namespace["request"] = SimpleNamespace(args=SimpleNamespace(get=lambda key, type=None: 1))
    namespace["security_manager"] = SimpleNamespace(
        get_user_by_id=lambda user_id: SimpleNamespace(get_full_name=lambda: "Ada Admin", username="admin")
    )
    return api, namespace


def test_metric_list_reports_state_formula_and_reason_and_skips_the_default_count():
    dataset = _dataset()
    dataset.columns[0].__dict__.update(verbose_name="Temperature", type="FLOAT", is_dttm=False)
    note_column = SimpleNamespace(column_name="note", is_active=True, groupby=False, filterable=False, expression=None)
    dataset.columns.append(note_column)
    metric_fields = {"verbose_name": None, "description": None, "d3format": ",.1f"}
    dataset.metrics[0].__dict__.update(metric_fields)
    dataset.metrics += [
        SimpleNamespace(id=5, metric_name="count", expression="COUNT(*)", **metric_fields),
        SimpleNamespace(id=6, metric_name="spread", expression="MAX(temperature) - MIN(temperature)", **metric_fields),
    ]
    contract = _MetricContract(dataset.id, 4, owner_id=3)
    contract.status, contract.approver_id = "approved", 3
    contract.expression_hash = metric_contract_hash(dataset, dataset.metrics[0])
    api, _ = _metric_list_api(dataset, [contract])

    status, payload = api.list_metric_contracts()

    assert status == 200
    approved, spread = payload["metrics"]
    assert (approved["metric_name"], spread["metric_name"]) == ("average_temperature", "spread")
    assert approved["state"] == "approved" and approved["ineligibility"] is None
    assert approved["formula"]["aggregation"] == "AVG" and approved["formula"]["measure_column"] == "temperature"
    assert approved["contract"]["approver_name"] == "Ada Admin" and "expression_hash" not in approved["contract"]
    assert spread["state"] == "ineligible" and spread["contract"] is None
    assert spread["ineligibility"] == METRIC_CONTRACT_RULE
    assert [column["column_name"] for column in payload["datasets"][0]["columns"]] == ["temperature"]


def test_metric_list_requires_admin_and_a_database():
    dataset = _dataset()
    api, namespace = _metric_list_api(dataset, [])
    namespace["request"] = SimpleNamespace(args=SimpleNamespace(get=lambda key, type=None: None))
    assert api.list_metric_contracts()[0] == 400
    namespace["current_user"].roles = []
    assert api.list_metric_contracts()[0] == 403


def test_route_source_has_no_sqllab_or_raw_execution_path():
    source = ROUTE_PATH.read_text(encoding="utf-8").lower()
    assert "sqllab" not in source and ".engine.execute" not in source
