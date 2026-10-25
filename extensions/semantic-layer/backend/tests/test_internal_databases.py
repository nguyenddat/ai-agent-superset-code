"""The AI Agent reporting connection is marked internal and stays out of the Semantic Layer's dataset pickers.

Like the other route tests, this reads the route source instead of importing Superset.
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

ROUTE_PATH = Path(__file__).parents[1] / "src" / "text_to_bi" / "superset_semantic_layer" / "modules" / "catalog" / "route.py"


def _route_tree():
    return ast.parse(ROUTE_PATH.read_text(encoding="utf-8"))


def _is_internal_dataset():
    function = next(
        node for node in _route_tree().body if isinstance(node, ast.FunctionDef) and node.name == "_is_internal_dataset"
    )
    namespace = {"json": json, "SqlaTable": object, "INTERNAL_DATABASE_FLAG": "text_to_bi_internal"}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROUTE_PATH), "exec"), namespace)  # noqa: S102
    return namespace["_is_internal_dataset"]


def _dataset(extra):
    return SimpleNamespace(database=SimpleNamespace(extra=extra))


def test_only_a_connection_flagged_internal_is_skipped():
    is_internal = _is_internal_dataset()

    assert is_internal(_dataset(json.dumps({"text_to_bi_internal": True})))
    assert not is_internal(_dataset(json.dumps({"text_to_bi_internal": "yes"})))
    assert not is_internal(_dataset(json.dumps({"engine_params": {}})))
    assert not is_internal(_dataset(None))
    assert not is_internal(_dataset("not json"))
    assert not is_internal(SimpleNamespace())


def test_every_all_dataset_listing_skips_internal_connections():
    api = next(node for node in _route_tree().body if isinstance(node, ast.ClassDef) and node.name == "SemanticLayerAPI")
    methods = {node.name: node for node in api.body if isinstance(node, ast.FunctionDef)}

    for name in ("get_reference_options", "glossary_options"):
        calls = {node.func.id for node in ast.walk(methods[name]) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert "_is_internal_dataset" in calls, name
