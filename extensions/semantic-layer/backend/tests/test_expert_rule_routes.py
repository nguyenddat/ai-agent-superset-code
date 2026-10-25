"""Route policy tests that avoid importing Superset's runtime dependencies."""

import ast
import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from flask import Flask

ROUTE_PATH = Path(__file__).parents[1] / "src" / "text_to_bi" / "superset_semantic_layer" / "modules" / "expert_rules" / "route.py"
ENDPOINTS = {
    "create_rule": ("/expert-rules", "POST"),
    "update_rule": ("/expert-rules/<int:rule_id>/draft", "PUT"),
    "approve": ("/expert-rules/<int:rule_id>/approve", "POST"),
    "revoke": ("/expert-rules/<int:rule_id>/revoke", "POST"),
    "audit": ("/expert-rules/<int:rule_id>/audit", "GET"),
    "discover": ("/expert-rules/discover", "GET"),
    "list_rules": ("/expert-rules", "GET"),
    "rule_options": ("/expert-rules/options", "GET"),
}


def _name(node):
    if isinstance(node, ast.Call):
        return _name(node.func)
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def test_routes_are_registered_and_mutations_are_admin_csrf_protected():
    tree = ast.parse(ROUTE_PATH.read_text(encoding="utf-8"))
    api = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ExpertRuleAPI")
    methods = {node.name: node for node in api.body if isinstance(node, ast.FunctionDef)}
    for name, (path, verb) in ENDPOINTS.items():
        method = methods[name]
        decorators = [_name(item) for item in method.decorator_list]
        expose = next(item for item in method.decorator_list if _name(item) == "expose")
        assert expose.args[0].value == path
        assert next(k.value.elts[0].value for k in expose.keywords if k.arg == "methods") == verb
        assert "protect" in decorators and "safe" in decorators
        text = ast.unparse(method)
        if verb != "GET":
            assert "_csrf_protected" in decorators and "self._is_admin()" in text
        if name == "discover":
            assert "can_access_datasource" in text and "redact" in text


def test_route_has_rollback_and_conflict_handling_without_raw_sql_execution():
    source = ROUTE_PATH.read_text(encoding="utf-8")
    assert "db.session.rollback()" in source
    assert "response(409" in source
    assert "execute(" not in source
    assert "text(" not in source
    assert "__table__.create" not in source
    assert "_ensure_tables" not in source
    assert "_linked_target_authorized" in source


class _Query:
    def __init__(self, values):
        self.values = values
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def order_by(self, *_):
        return self

    def all(self):
        return [value for value in self.values if all(getattr(value, key, None) == item for key, item in self.filters.items())]

    def one_or_none(self):
        values = self.all()
        return values[0] if len(values) == 1 else None


def _load_route(monkeypatch, *, csrf_error=False, allowed_datasets=()):
    """Load route.py with local stubs; no Superset package or metadata DB is used."""
    package = "text_to_bi.superset_semantic_layer.modules.expert_rules"
    route_name = f"{package}.route_isolated"
    current_user = SimpleNamespace(id=42, is_authenticated=True, roles=[SimpleNamespace(name="Admin")])
    session = SimpleNamespace(commit_calls=0, rollback_calls=0)
    session.commit = lambda: setattr(session, "commit_calls", session.commit_calls + 1)
    session.rollback = lambda: setattr(session, "rollback_calls", session.rollback_calls + 1)
    session.get = lambda *_: None
    db = SimpleNamespace(session=session)

    def identity_decorator(*args, **kwargs):
        if args and callable(args[0]) and not kwargs:
            return args[0]
        return lambda method: method

    api_module = types.ModuleType("flask_appbuilder.api")
    api_module.expose = api_module.permission_name = api_module.protect = identity_decorator
    api_module.safe = identity_decorator
    login_module = types.ModuleType("flask_login")
    login_module.current_user = current_user
    csrf_module = types.ModuleType("flask_wtf.csrf")
    validation_error = type("ValidationError", (Exception,), {})
    csrf_module.validate_csrf = lambda _: (_ for _ in ()).throw(validation_error()) if csrf_error else None
    wtforms_module = types.ModuleType("wtforms")
    wtforms_module.ValidationError = validation_error
    superset_module = types.ModuleType("superset")
    superset_module.db = db
    reviewer = SimpleNamespace(username="reviewer", get_full_name=lambda: "Bao Reviewer")
    superset_module.security_manager = SimpleNamespace(
        raise_for_access=lambda datasource: None if datasource.id in allowed_datasets else (_ for _ in ()).throw(Exception()),
        get_user_by_id=lambda user_id: reviewer if user_id == 42 else None,
    )
    sqla_module = types.ModuleType("superset.connectors.sqla.models")
    sqla_module.SqlaTable = type("SqlaTable", (), {})
    exception_module = types.ModuleType("superset.exceptions")
    exception_module.SupersetSecurityException = Exception
    rest_api_module = types.ModuleType("superset_core.rest_api.api")

    class RestApi:
        def response(self, status, **payload): return status, payload
        def response_400(self, **payload): return 400, payload
        def response_500(self, **payload): return 500, payload

    rest_api_module.RestApi = RestApi
    rest_decorators = types.ModuleType("superset_core.rest_api.decorators")
    rest_decorators.api = identity_decorator
    models = types.ModuleType("text_to_bi.superset_semantic_layer.models.expert_rule")
    models.ExpertRule = type("ExpertRule", (), {})
    models.ExpertRuleRevision = type("ExpertRuleRevision", (), {})
    models.ExpertRuleLink = type("ExpertRuleLink", (), {})
    models.ExpertRuleAuditEvent = type("ExpertRuleAuditEvent", (), {"id": object()})
    column_dictionary = types.ModuleType("text_to_bi.superset_semantic_layer.models.column_dictionary")
    column_dictionary.ColumnDictionary = type("ColumnDictionary", (), {})
    dataset_dictionary = types.ModuleType("text_to_bi.superset_semantic_layer.models.dataset_dictionary")
    dataset_dictionary.DatasetDictionary = type("DatasetDictionary", (), {})
    glossary = types.ModuleType("text_to_bi.superset_semantic_layer.models.glossary_term")
    glossary.GlossaryTermLink = type("GlossaryTermLink", (), {})
    glossary.GlossaryTerm = type("GlossaryTerm", (), {})
    glossary.GlossaryTermRevision = type("GlossaryTermRevision", (), {})
    metric = types.ModuleType("text_to_bi.superset_semantic_layer.models.metric_contract")
    metric.MetricContract = type("MetricContract", (), {})
    contracts = types.ModuleType("text_to_bi.superset_semantic_layer.modules.semantic_query.contracts")
    contracts.contract_is_approved_current = lambda *_: True
    contracts.metric_contract_hash = lambda *_: "live"
    for name, module in {
        "flask_appbuilder.api": api_module, "flask_login": login_module, "flask_wtf.csrf": csrf_module, "wtforms": wtforms_module,
        "superset": superset_module, "superset.connectors.sqla.models": sqla_module, "superset.exceptions": exception_module,
        "superset_core.rest_api.api": rest_api_module, "superset_core.rest_api.decorators": rest_decorators,
        models.__name__: models, column_dictionary.__name__: column_dictionary, dataset_dictionary.__name__: dataset_dictionary,
        glossary.__name__: glossary, metric.__name__: metric, contracts.__name__: contracts,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location(route_name, ROUTE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, route_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, current_user, session


def test_mutation_route_enforces_csrf_admin_and_rolls_back_validation_errors(monkeypatch):
    app = Flask(__name__)
    route, user, session = _load_route(monkeypatch, allowed_datasets={7})
    api = route.ExpertRuleAPI()
    with app.test_request_context("/", method="POST", json={}):
        user.roles = []
        assert api.create_rule()[0] == 403
    with app.test_request_context("/", method="POST", json={}):
        user.roles = [SimpleNamespace(name="Admin")]
        user.is_authenticated = False
        assert api.create_rule()[0] == 403
    user.is_authenticated = True
    user.roles = [SimpleNamespace(name="Admin")]
    route.create_draft = lambda *_: (_ for _ in ()).throw(route.ExpertRuleValidationError("invalid"))
    with app.test_request_context("/", method="POST", json={}):
        assert api.create_rule()[0] == 400
    assert session.rollback_calls == 1

    csrf_route, _, _ = _load_route(monkeypatch, csrf_error=True, allowed_datasets={7})
    with app.test_request_context("/", method="POST", json={}):
        assert csrf_route.ExpertRuleAPI().create_rule()[0] == 403


def test_discovery_keeps_rule_when_only_unrelated_glossary_link_is_denied_and_omits_stale_or_cross_dataset(monkeypatch):
    app = Flask(__name__)
    route, _, session = _load_route(monkeypatch, allowed_datasets={7})
    revision = SimpleNamespace(id=1, rule_id=1, revision_number=2, lifecycle_version=3, status="approved", is_current=True, name="Final only", conditions=[], exceptions=[], examples=[])
    stale = SimpleNamespace(id=2, rule_id=1, revision_number=3, lifecycle_version=4, status="approved", is_current=True, name="Stale", conditions=[], exceptions=[], examples=[])
    denied = SimpleNamespace(id=3, rule_id=2, revision_number=1, lifecycle_version=1, status="approved", is_current=True, name="Denied", conditions=[], exceptions=[], examples=[])
    rules = {1: SimpleNamespace(dataset_id=7), 2: SimpleNamespace(dataset_id=8)}
    links = {
        1: [SimpleNamespace(kind="dataset", target_id=7, dataset_id=7, fingerprint="dataset"), SimpleNamespace(kind="glossary", target_id=3, dataset_id=7, fingerprint="glossary")],
        2: [SimpleNamespace(kind="dataset", target_id=7, dataset_id=7, fingerprint="old")],
        3: [SimpleNamespace(kind="dataset", target_id=8, dataset_id=8, fingerprint="dataset")],
    }
    session.query = lambda model: _Query([revision, stale, denied] if model is route.ExpertRuleRevision else links.get(0, []))
    def query(model):
        query_values = [revision, stale, denied] if model is route.ExpertRuleRevision else []
        result = _Query(query_values)
        if model is route.ExpertRuleLink:
            result.all = lambda: links.get(result.filters.get("revision_id"), [])
        return result
    session.query = query
    session.get = lambda model, key: rules[key] if model is route.ExpertRule else None
    api = route.ExpertRuleAPI()
    api._dataset = lambda dataset_id: SimpleNamespace(id=dataset_id)
    api._glossary = lambda _: [SimpleNamespace(dataset_id=7), SimpleNamespace(dataset_id=8)]
    api._fingerprint = lambda kind, _, __: {"dataset": "dataset", "glossary": "glossary"}[kind]
    with app.test_request_context("/", method="GET"):
        status, body = api.discover()
    assert status == 200
    assert [item["name"] for item in body["rules"]] == ["Final only"]
    assert body["rules"][0]["lifecycle_version"] == 3
    # Discovery names what the rule links to, so a consumer can join it to catalog metrics and glossary terms.
    assert (body["rules"][0]["dataset_id"], body["rules"][0]["glossary_term_ids"], body["rules"][0]["metric_ids"]) == (7, [3], [])


def test_serialized_rule_and_audit_expose_lifecycle_version(monkeypatch):
    app = Flask(__name__)
    route, _, session = _load_route(monkeypatch)
    revision = SimpleNamespace(
        rule_id=1, revision_number=2, lifecycle_version=3, status="approved", name="Final only", conditions=[], exceptions=[], examples=[]
    )
    event = SimpleNamespace(
        rule_id=1, event_type="approved", revision_number=2, lifecycle_version=3, actor_id=42, reason="Đã đối chiếu",
        occurred_at=datetime.now(timezone.utc),
    )
    session.query = lambda _: _Query([event])
    api = route.ExpertRuleAPI()
    assert api._serialize(revision)["lifecycle_version"] == 3
    assert api._serialize(revision)["schema_version"] == 2
    with app.test_request_context("/", method="GET"):
        status, body = api.audit(1)
    assert status == 200
    assert body["audit"] == [{
        "action": "approved", "revision": 2, "lifecycle_version": 3, "actor_id": 42, "actor_name": "Bao Reviewer",
        "reason": "Đã đối chiếu", "occurred_at": event.occurred_at.isoformat(),
    }]


def test_self_approval_is_refused_with_403_and_rolled_back(monkeypatch):
    app = Flask(__name__)
    route, _, session = _load_route(monkeypatch)
    api = route.ExpertRuleAPI()
    api._revision = lambda _: SimpleNamespace(rule_id=1)
    received = {}

    def refuse(*_, require_second_reviewer):
        received["require_second_reviewer"] = require_second_reviewer
        raise route.ExpertRuleSelfApprovalError("Người soạn rule không thể tự duyệt")

    route.approve_rule = refuse
    app.config["TEXT_TO_BI_REQUIRE_SECOND_REVIEWER"] = True
    with app.test_request_context("/", method="POST", json={"expected_revision": 1}):
        status, body = api.approve(1)
    assert received == {"require_second_reviewer": True}
    assert status == 403 and "tự duyệt" in body["message"]
    assert session.rollback_calls == 1 and session.commit_calls == 0


def test_review_list_and_options_are_admin_only(monkeypatch):
    app = Flask(__name__)
    route, user, _ = _load_route(monkeypatch)
    user.roles = []
    api = route.ExpertRuleAPI()
    with app.test_request_context("/", method="GET"):
        assert api.list_rules()[0] == 403
        assert api.rule_options()[0] == 403


def test_review_revisions_prefer_the_current_one_and_fall_back_to_the_latest(monkeypatch):
    route, _, session = _load_route(monkeypatch)
    revisions = [
        SimpleNamespace(rule_id=1, revision_number=1, is_current=False),
        SimpleNamespace(rule_id=1, revision_number=2, is_current=True),
        SimpleNamespace(rule_id=2, revision_number=1, is_current=False),
        SimpleNamespace(rule_id=2, revision_number=2, is_current=False),
    ]
    route.ExpertRuleRevision.revision_number = object()
    session.query = lambda _: _Query(revisions)
    chosen = route.ExpertRuleAPI._review_revisions()
    assert [(item.rule_id, item.revision_number) for item in chosen] == [(1, 2), (2, 2)]


def test_an_approved_rule_with_a_changed_link_is_outdated(monkeypatch):
    route, _, _ = _load_route(monkeypatch)
    api = route.ExpertRuleAPI()
    api._fingerprint = lambda kind, _, __: {"dataset": "dataset", "metric": "metric-changed"}[kind]
    approved = SimpleNamespace(status="approved", is_current=True)
    links = [
        SimpleNamespace(kind="dataset", target_id=7, dataset_id=7, fingerprint="dataset"),
        SimpleNamespace(kind="metric", target_id=9, dataset_id=7, fingerprint="metric-at-approval"),
    ]
    assert api._review_state(approved, links) == "outdated"
    assert api._review_state(approved, links[:1]) == "approved"
    assert api._review_state(SimpleNamespace(status="draft", is_current=True), links) == "draft"
