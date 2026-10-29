import ast
from types import SimpleNamespace

from catalog_source import api_methods, compile_into, module_function

from text_to_bi.superset_semantic_layer.core.exceptions import AdminRequiredError
from text_to_bi.superset_semantic_layer.modules.glossary.exceptions import (
    GlossaryConflictError,
    GlossarySelfApprovalError,
    GlossaryValidationError,
)

ADMIN_ENDPOINTS = {
    "list_glossary": ("/glossary", "GET"),
    "glossary_options": ("/glossary/options", "GET"),
    "create_glossary": ("/glossary", "POST"),
    "update_glossary_draft": ("/glossary/<int:term_id>/draft", "PUT"),
    "approve_glossary": ("/glossary/<int:term_id>/approve", "POST"),
    "revoke_glossary": ("/glossary/<int:term_id>/revoke", "POST"),
    "glossary_audit": ("/glossary/<int:term_id>/audit", "GET"),
}


def _call_name(node):
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _decorator_calls(method):
    return [_call_name(decorator) for decorator in method.decorator_list]


def _route(method):
    expose = next(decorator for decorator in method.decorator_list if _call_name(decorator) == "expose")
    return expose.args[0].value, next(
        keyword.value.elts[0].value for keyword in expose.keywords if keyword.arg == "methods"
    )


class _GlossaryResponseAPI:
    def response(self, status, **payload):
        return status, payload

    def response_400(self, **payload):
        return self.response(400, **payload)


class _CurrentRevisionQuery:
    def __init__(self, revision):
        self.revision = revision

    def filter_by(self, **_kwargs):
        return self

    def one_or_none(self):
        return self.revision


def _update_handler(payload, update_draft):
    """Compile the real handler with Superset's request/session boundary faked."""
    methods = api_methods()
    handler = methods["update_glossary_draft"]
    # Keep only @handle_errors, which turns the module's errors into responses.
    handler.decorator_list = [item for item in handler.decorator_list if _call_name(item) == "handle_errors"]
    api = ast.ClassDef(
        name="HarnessAPI",
        bases=[ast.Name(id="RestApi", ctx=ast.Load())],
        keywords=[],
        body=[handler],
        decorator_list=[],
    )
    current = SimpleNamespace(revision_number=3, term=SimpleNamespace(id=7))
    session = SimpleNamespace(
        query=lambda _model: _CurrentRevisionQuery(current),
        get=lambda *_args: None,
        commit=lambda: None,
        rollback=lambda: None,
    )
    namespace = {
        "RestApi": _GlossaryResponseAPI,
        "GlossaryTermRevision": object,
        "SqlaTable": object,
        "db": SimpleNamespace(session=session),
        "request": SimpleNamespace(get_json=lambda silent=True: payload),
        "current_user": SimpleNamespace(id=42),
        "ensure_dictionary_tables": lambda: None,
        "update_draft": update_draft,
        "require_admin": lambda: None,
    }
    compile_into(namespace, api)
    instance = namespace["HarnessAPI"]()
    instance._glossary_user_exists = lambda _user_id: True
    instance._glossary_metric_approved = lambda _dataset, _metric: True
    instance._glossary_term = lambda term, revisions: {"id": term.id, "revisions": len(revisions)}
    return instance, current, GlossaryValidationError, GlossaryConflictError


def _frontend_draft_payload(**overrides):
    payload = {
        "canonical_name": "Average temperature",
        "definition": "Mean recorded temperature.",
        "synonyms": ["mean temperature"],
        "provenance": "manual",
        "owner_id": 1,
        "steward_id": 2,
        "links": [{"kind": "dataset", "dataset_id": 7}],
        "expected_revision": 3,
    }
    payload.update(overrides)
    return payload


def test_admin_glossary_management_routes_are_explicitly_guarded_and_csrf_protected():
    methods = api_methods()
    for name, expected_route in ADMIN_ENDPOINTS.items():
        method = methods[name]
        decorators = _decorator_calls(method)
        assert _route(method) == expected_route
        assert "protect" in decorators and "safe" in decorators and "permission_name" in decorators
        assert decorators[-1] == "handle_errors"
        if expected_route[1] != "GET":
            assert "csrf_protected" in decorators and "rollback_on_error" in decorators
        assert "require_admin()" in ast.unparse(method)
    assert (AdminRequiredError.status, AdminRequiredError.message) == (403, "Admin access required.")


def test_management_routes_delegate_to_governed_service_with_expected_revision_and_actor():
    methods = api_methods()
    for name in ("create_glossary", "update_glossary_draft", "approve_glossary", "revoke_glossary"):
        source = ast.unparse(methods[name])
        assert "current_user.id" in source
    for name in ("update_glossary_draft", "approve_glossary", "revoke_glossary"):
        source = ast.unparse(methods[name])
        assert "expected_revision" in source
    assert "create_draft" in ast.unparse(methods["create_glossary"])
    assert "update_draft" in ast.unparse(methods["update_glossary_draft"])
    assert "approve" in ast.unparse(methods["approve_glossary"])
    assert "revoke" in ast.unparse(methods["revoke_glossary"])


def test_update_draft_executes_frontend_payload_with_revision_token_separate_from_service_content():
    received = {}

    def update_draft(_session, current, payload, expected, actor_id, _dataset, _user, _metric_is_approved):
        received.update(current=current, payload=payload, expected=expected, actor_id=actor_id)
        return SimpleNamespace(term=SimpleNamespace(id=7))

    api, current, _, _ = _update_handler(_frontend_draft_payload(), update_draft)
    status, body = api.update_glossary_draft(7)

    assert status == 200
    assert body["term"] == {"id": 7, "revisions": 1}
    assert received["current"] is current and received["expected"] == 3 and received["actor_id"] == 42
    expected_payload = _frontend_draft_payload()
    expected_payload.pop("expected_revision")
    assert received["payload"] == expected_payload
    assert "expected_revision" not in received["payload"]


def test_update_draft_maps_service_conflict_to_409():
    api, _, _, conflict_error = _update_handler(
        _frontend_draft_payload(), lambda *_args: (_ for _ in ()).throw(conflict_error("stale revision"))
    )
    status, body = api.update_glossary_draft(7)
    assert (status, body) == (409, {"message": "stale revision"})


def test_update_draft_rejects_non_object_or_missing_revision_before_service_call():
    called = []
    api, _, _, _ = _update_handler(None, lambda *_args: called.append(True))
    status, body = api.update_glossary_draft(7)
    assert (status, body) == (400, {"message": "expected_revision is required."})
    assert called == []


def test_admin_routes_keep_service_errors_generic_and_rollback_unexpected_failures():
    rollback = module_function("rollback_on_error")
    session = type(
        "Session", (), {"rollbacks": 0, "rollback": lambda self: setattr(self, "rollbacks", self.rollbacks + 1)}
    )()
    namespace = {
        "wraps": lambda method: lambda wrapper: wrapper,
        "db": type("DB", (), {"session": session})(),
        "logger": type("Log", (), {"exception": lambda *_: None})(),
    }
    compile_into(namespace, rollback)
    wrapped = namespace["rollback_on_error"](lambda _: (_ for _ in ()).throw(RuntimeError("internal detail")))
    response = type("API", (), {"response_500": lambda self, **payload: (500, payload)})()
    assert wrapped(response) == (500, {"message": "Could not save the change."})
    assert session.rollbacks == 1


def test_audit_is_admin_only_read_only_and_cannot_be_used_for_cross_term_id_lookup():
    method = api_methods()["glossary_audit"]
    source = ast.unparse(method)
    assert "term_id" in source and "audit" in source.lower()
    assert "current_user.id" not in source  # audit visibility is role-based, not caller-supplied identity.
    assert "request.args" not in source  # no alternate revision/term ID can override the path scope.


def test_approval_passes_the_second_reviewer_setting_and_answers_self_approval_with_403():
    source = ast.unparse(api_methods()["_glossary_lifecycle"])
    assert "second_reviewer_required()" in source
    assert GlossarySelfApprovalError.status == 403 and "không thể tự duyệt" in GlossarySelfApprovalError.message


def test_list_reports_review_state_reviewers_and_the_second_reviewer_setting():
    source = ast.unparse(api_methods()["list_glossary"]) + ast.unparse(api_methods()["_glossary_review_entry"])
    for field in (
        "state",
        "author_name",
        "approver_name",
        "revoker_name",
        "current_user_id",
        "require_second_reviewer",
    ):
        assert f"'{field}'" in source or f"{field}=" in source
    assert "'outdated'" in source
