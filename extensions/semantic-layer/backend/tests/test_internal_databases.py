import ast
import json
from types import SimpleNamespace

from catalog_source import api_methods, compile_into, module_function


def _is_internal_dataset():
    namespace = {"json": json, "SqlaTable": object, "INTERNAL_DATABASE_FLAG": "text_to_bi_internal"}
    compile_into(namespace, module_function("is_internal_dataset"))
    return namespace["is_internal_dataset"]


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
    methods = api_methods()

    for name in ("get_reference_options", "glossary_options"):
        calls = {
            node.func.id
            for node in ast.walk(methods[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "is_internal_dataset" in calls, name
