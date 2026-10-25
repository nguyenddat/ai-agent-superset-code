import ast
from pathlib import Path

ROUTE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "text_to_bi"
    / "superset_semantic_layer"
    / "modules"
    / "catalog"
    / "route.py"
)


def test_catalog_route_uses_python_310_compatible_utc_timezone():
    tree = ast.parse(ROUTE_PATH.read_text(encoding="utf-8"))

    datetime_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "datetime"
    ]
    assert all(alias.name != "UTC" for node in datetime_imports for alias in node.names)

    timezone_utc_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "datetime"
        and node.func.attr == "now"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Attribute)
        and isinstance(node.args[0].value, ast.Name)
        and node.args[0].value.id == "timezone"
        and node.args[0].attr == "utc"
    ]
    assert len(timezone_utc_calls) == 2
