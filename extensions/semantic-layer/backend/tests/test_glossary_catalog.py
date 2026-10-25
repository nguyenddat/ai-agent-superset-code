"""Consumer-discovery contract tests for governed glossary terms."""

import ast
from pathlib import Path
from types import SimpleNamespace

ROUTE_PATH = Path(__file__).parents[1] / "src" / "text_to_bi" / "superset_semantic_layer" / "modules" / "catalog" / "route.py"


def _route_method(name):
    tree = ast.parse(ROUTE_PATH.read_text(encoding="utf-8"))
    api = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SemanticLayerAPI")
    return next(node for node in api.body if isinstance(node, ast.FunctionDef) and node.name == name)


def _discovery_method():
    return _route_method("glossary_discovery")


def _discovery_source():
    """The endpoint and the helper it shares with the semantic catalog, which holds the filtering."""
    return ast.unparse(_discovery_method()) + "\n" + ast.unparse(_route_method("_discoverable_glossary_terms"))


def _call_name(node):
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


class _DiscoveryResponseAPI:
    def response(self, status, **payload):
        return status, payload


class _RevisionQuery:
    def __init__(self, revisions):
        self.revisions = revisions

    def filter_by(self, **kwargs):
        assert kwargs == {"status": "approved", "is_current": True}
        return self

    def all(self):
        return self.revisions


def _discovery_handler(revisions, datasets, links_by_revision, allowed_dataset_ids):
    """Execute the real discovery handler, without importing Superset."""
    method = _discovery_method()
    method.decorator_list = []
    helper = _route_method("_discoverable_glossary_terms")
    body = [method, helper]
    api = ast.ClassDef(name="HarnessAPI", bases=[ast.Name(id="RestApi", ctx=ast.Load())], keywords=[], body=body, decorator_list=[])

    def query(model):
        assert model is revision_model
        return _RevisionQuery(revisions)

    revision_model = object()
    namespace = {
        "RestApi": _DiscoveryResponseAPI,
        "Any": object,
        "GlossaryTermRevision": revision_model,
        "SqlaTable": object,
        "db": SimpleNamespace(session=SimpleNamespace(query=query, get=lambda _model, key: datasets.get(key))),
        "_ensure_dictionary_tables": lambda: None,
        "glossary_link_fingerprint": lambda dataset, kind, target: f"{dataset.id}:{kind}:{getattr(target, 'id', '')}",
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[api], type_ignores=[])), str(ROUTE_PATH), "exec"), namespace)  # noqa: S102
    instance = namespace["HarnessAPI"]()
    instance._glossary_links = lambda revision_id: links_by_revision.get(revision_id, [])
    instance._can_access_semantic_query_dataset = lambda dataset: dataset.id in allowed_dataset_ids
    instance._glossary_link_target = lambda link, _dataset: link.target
    return instance


def test_discovery_is_authenticated_read_only_and_not_admin_gated():
    method = _discovery_method()
    decorators = [_call_name(item) for item in method.decorator_list]
    expose = next(item for item in method.decorator_list if _call_name(item) == "expose")
    assert expose.args[0].value == "/glossary/discovery"
    assert next(keyword.value.elts[0].value for keyword in expose.keywords if keyword.arg == "methods") == "GET"
    assert "protect" in decorators and "safe" in decorators and "permission_name" in decorators
    assert "_is_admin" not in ast.unparse(method)


def test_discovery_filters_to_approved_current_live_links_before_serialization():
    source = _discovery_source()
    assert "approved" in source and "is_current" in source
    assert "fingerprint" in source.lower()
    assert "raise_for_access" in source or "_can_access_semantic_query_dataset" in source
    assert "links" in source


def test_discovery_contract_redacts_denied_dataset_b_and_hides_terms_without_allowed_links():
    """The handler must redact at link level; merely filtering term rows leaks B's identifiers."""
    source = _discovery_source()
    # The serializer must construct a filtered link collection and gate the term on it.
    assert "visible_links" in source or "authorized_links" in source or "allowed_links" in source
    assert "if not" in source and "links" in source
    # Discovery is a consumer projection: no unsafe provenance/source fields may be emitted.
    assert "source_reference" not in source and "source_hash" not in source


def test_discovery_cannot_accept_a_client_selected_dataset_or_link_id_scope():
    """A valid ID from dataset B must never widen discovery for a caller allowed only dataset A."""
    source = _discovery_source()
    assert "request.args" not in source
    assert "request.get_json" not in source


def test_discovery_executes_link_level_redaction_and_omits_terms_without_visible_links():
    allowed = SimpleNamespace(id=7)
    denied = SimpleNamespace(id=8)
    first = SimpleNamespace(id=101, term_id=1, definition="Allowed", synonyms=[], term=SimpleNamespace(canonical_name="A"))
    second = SimpleNamespace(id=102, term_id=2, definition="Denied", synonyms=[], term=SimpleNamespace(canonical_name="B"))
    allowed_link = SimpleNamespace(kind="dataset", dataset_id=7, column_name=None, metric_id=None, target=None, fingerprint="7:dataset:")
    denied_link = SimpleNamespace(kind="dataset", dataset_id=8, column_name=None, metric_id=None, target=None, fingerprint="8:dataset:")
    api = _discovery_handler([first, second], {7: allowed, 8: denied}, {101: [allowed_link], 102: [denied_link]}, {7})

    status, body = api.glossary_discovery()

    assert status == 200
    assert body == {
        "terms": [
            {
                "term_id": 1,
                "canonical_name": "A",
                "definition": "Allowed",
                "synonyms": [],
                "links": [{"kind": "dataset", "dataset_id": 7, "column_name": None, "metric_id": None}],
            }
        ]
    }
    assert "B" not in repr(body) and "8" not in repr(body)


def test_drafts_ai_candidates_revoked_and_stale_objects_are_not_consumer_knowledge():
    source = _discovery_source()
    assert "draft" not in source or "!= 'draft'" in source or '!= "draft"' in source
    assert "revoked" not in source or "!= 'revoked'" in source or '!= "revoked"' in source
    # AI provenance is permitted only after explicit approval, which the approved/current filter enforces.
    assert "approved" in source and "is_current" in source
