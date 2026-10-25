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

    def desc(self):
        return self


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


class _MetricContractEvent:
    dataset_id = metric_id = created_at = id = _ModelField()

    def __init__(self, **fields):
        self.__dict__.update(fields)


class _MetricDefinition:
    dataset_id = metric_id = _ModelField()

    def __init__(self, dataset_id, metric_id):
        self.dataset_id, self.metric_id = dataset_id, metric_id
        self.business_definition = self.unit = self.steward_id = None


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
        "list_metric_contracts", "_user_names", "_active_users", "_metric_definition", "_serialize_metric_definition",
        "_review_reason", "_record_metric_event", "save_metric_definition", "list_metric_contract_events",
        "_second_reviewer_required",
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
        "MetricContractEvent": _MetricContractEvent, "MetricDefinition": _MetricDefinition,
        "METRIC_REVIEW_REASON_MAX_LENGTH": 2000, "METRIC_DEFINITION_MAX_LENGTH": 4000, "METRIC_UNIT_MAX_LENGTH": 64,
    }
    module = ast.Module(body=[cap_node, class_node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROUTE_PATH), "exec"), namespace)  # noqa: S102
    api = namespace["SemanticLayerAPI"]()
    # Proposing needs a business definition; tests about other rules start from a metric that has one.
    api._metric_definition = lambda *_: SimpleNamespace(business_definition="Average air temperature.")
    return api, namespace


def _use_request_body(namespace, body):
    namespace["request"] = SimpleNamespace(get_json=lambda silent=True: body, args=namespace["request"].args)


def _as_user(namespace, user_id):
    admin_role = SimpleNamespace(name="Admin")
    namespace["current_user"] = SimpleNamespace(is_authenticated=True, id=user_id, roles=[admin_role])


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
    session.add = lambda item: None if isinstance(item, _MetricContractEvent) else snapshots.append(dict(vars(item)))
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
    _as_user(namespace, 5)
    assert api.approve_metric_contract(dataset.id, 4)[0] == 200
    assert holder["contract"].status == "approved" and holder["contract"].approver_id == 5
    _use_request_body(namespace, {"reason": "Formula double counts hourly rows."})
    assert api.revoke_metric_contract(dataset.id, 4)[0] == 200
    assert holder["contract"].status == "revoked"
    events = [item for item in namespace["db"].session.added if isinstance(item, _MetricContractEvent)]
    assert [(event.action, event.actor_id) for event in events] == [("candidate", 3), ("approve", 5), ("revoke", 5)]
    assert events[2].reason == "Formula double counts hourly rows." and events[0].expression == 'AVG("temperature")'


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
    access_denied = type("AccessDenied", (Exception,), {})
    namespace["execute_approved_chart_query"] = lambda *args, **kwargs: (_ for _ in ()).throw(access_denied())
    assert api.execute_metric_contract(dataset.id, metric.id)[0] == 403
    namespace["current_app"].config["SEMANTIC_QUERY_MAX_ROWS"] = 10_000
    many_rows = {"colnames": ["city"], "data": [{"city": "A"}] * 1001}
    namespace["execute_approved_chart_query"] = lambda *args, **kwargs: many_rows
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
    chart_result = {"colnames": ["city"], "data": [], "query": executed_sql}
    namespace["execute_approved_chart_query"] = lambda *args, **kwargs: chart_result
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
    api._active_users = lambda: [{"id": 3, "name": "Ada Admin"}]
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


def _proposed_contract(dataset, owner_id=3):
    contract = _MetricContract(dataset.id, 4, owner_id=owner_id)
    contract.status, contract.expression = "candidate", dataset.metrics[0].expression
    contract.expression_hash = metric_contract_hash(dataset, dataset.metrics[0])
    return contract


def test_the_proposer_approves_alone_by_default():
    dataset = _dataset()
    api, _ = _route_api({dataset.id: dataset})
    contract = _proposed_contract(dataset, owner_id=3)
    api._contract_for = lambda *_: contract
    assert api.approve_metric_contract(dataset.id, 4)[0] == 200
    assert contract.status == "approved" and contract.approver_id == 3


def test_the_proposer_cannot_approve_when_a_second_reviewer_is_required():
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    namespace["current_app"].config["TEXT_TO_BI_REQUIRE_SECOND_REVIEWER"] = True
    contract = _proposed_contract(dataset, owner_id=3)
    api._contract_for = lambda *_: contract
    status, payload = api.approve_metric_contract(dataset.id, 4)
    assert status == 403 and "không thể tự duyệt" in payload["message"] and contract.status == "candidate"
    _as_user(namespace, 5)
    _use_request_body(namespace, {"reason": "  Checked against the hourly feed.  "})
    assert api.approve_metric_contract(dataset.id, 4)[0] == 200
    event = namespace["db"].session.added[-1]
    assert (event.action, event.actor_id, event.reason) == ("approve", 5, "Checked against the hourly feed.")


def test_proposing_again_makes_the_new_proposer_the_owner_and_needs_a_definition():
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    contract = _proposed_contract(dataset, owner_id=3)
    contract.status = "revoked"
    api._contract_for = lambda *_: contract
    _as_user(namespace, 5)
    assert api.create_metric_contract_candidate(dataset.id, 4)[0] == 201
    assert contract.owner_id == 5 and contract.status == "candidate"
    api._metric_definition = lambda *_: None
    status, payload = api.create_metric_contract_candidate(dataset.id, 4)
    assert status == 400 and "định nghĩa nghiệp vụ" in payload["message"]


def test_revoking_needs_a_reason_and_a_live_contract():
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    contract = _proposed_contract(dataset)
    api._contract_for = lambda *_: contract
    _use_request_body(namespace, {"reason": "   "})
    assert api.revoke_metric_contract(dataset.id, 4)[0] == 400 and contract.status == "candidate"
    _use_request_body(namespace, {"reason": "x" * 2001})
    assert api.revoke_metric_contract(dataset.id, 4)[0] == 400
    _use_request_body(namespace, {"reason": "Superseded."})
    assert api.revoke_metric_contract(dataset.id, 4)[0] == 200 and contract.status == "revoked"
    assert api.revoke_metric_contract(dataset.id, 4)[0] == 400


def test_metric_definition_is_validated_saved_and_logged():
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    api._metric_definition = lambda *_: None
    known_user = SimpleNamespace(get_full_name=lambda: "Bao Steward", username="bao")
    namespace["security_manager"] = SimpleNamespace(get_user_by_id=lambda user_id: known_user if user_id == 9 else None)
    for body in (
        {"business_definition": "  "},
        {"business_definition": "x" * 4001},
        {"business_definition": "Average.", "unit": "u" * 65},
        {"business_definition": "Average.", "steward_id": 42},
        {"business_definition": "Average.", "steward_id": True},
    ):
        _use_request_body(namespace, body)
        assert api.save_metric_definition(dataset.id, 4)[0] == 400, body
    _use_request_body(namespace, {"business_definition": " Average air temperature. ", "unit": " °C ", "steward_id": 9})
    status, payload = api.save_metric_definition(dataset.id, 4)
    assert status == 200
    assert payload["definition"] == {
        "business_definition": "Average air temperature.", "unit": "°C", "steward_id": 9, "steward_name": "Bao Steward",
    }
    assert namespace["db"].session.added[-1].action == "definition"
    namespace["current_user"].roles = []
    assert api.save_metric_definition(dataset.id, 4)[0] == 403


def test_metric_events_are_listed_newest_first_with_actor_names():
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    created_at = datetime(2026, 10, 25, 9, 30, tzinfo=timezone.utc)
    events = [
        _MetricContractEvent(id=2, action="approve", actor_id=5, reason="Checked.", expression="AVG(t)"),
        _MetricContractEvent(id=1, action="candidate", actor_id=3, reason=None, expression="AVG(t)"),
    ]

    class Query:
        def __init__(self, model):
            pass

        def filter(self, *_):
            return self

        def order_by(self, *_):
            return self

        def all(self):
            return events

    for event in events:
        event.created_at = created_at
    namespace["db"].session.query = Query
    names = {3: "Ada Admin", 5: "Bao Reviewer"}
    namespace["security_manager"] = SimpleNamespace(
        get_user_by_id=lambda user_id: SimpleNamespace(get_full_name=lambda: names[user_id], username="user")
    )
    status, payload = api.list_metric_contract_events(dataset.id, 4)
    assert status == 200
    assert [(event["action"], event["actor_name"]) for event in payload["events"]] == [
        ("approve", "Bao Reviewer"), ("candidate", "Ada Admin"),
    ]
    assert payload["events"][0]["created_at"] == "2026-10-25T09:30:00+00:00"


def test_only_administrators_may_preview_a_candidate(monkeypatch):
    dataset = _dataset()
    api, namespace = _route_api({dataset.id: dataset})
    contract = _proposed_contract(dataset)
    api._contract_for = lambda *_: contract
    api._can_access_semantic_query_dataset = lambda _: True
    _install_chartdata_stubs(monkeypatch)
    grants = []

    def run(*args, allow_candidate=False):
        grants.append(allow_candidate)
        return {"colnames": [], "data": []}

    namespace["execute_approved_chart_query"] = run
    status, payload = api.execute_metric_contract(dataset.id, 4)
    assert status == 200 and payload["preview"] is True
    namespace["current_user"].roles = []
    api.execute_metric_contract(dataset.id, 4)
    assert grants == [True, False]


def test_route_source_has_no_sqllab_or_raw_execution_path():
    source = ROUTE_PATH.read_text(encoding="utf-8").lower()
    assert "sqllab" not in source and ".engine.execute" not in source
