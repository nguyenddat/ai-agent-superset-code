import ast

from catalog_source import SOURCE_PATHS


def test_catalog_route_uses_python_310_compatible_utc_timezone():
    tree = ast.Module(
        body=[node for path in SOURCE_PATHS for node in ast.parse(path.read_text(encoding="utf-8")).body],
        type_ignores=[],
    )

    datetime_imports = [
        node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module == "datetime"
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
    # Approving and revoking a relationship contract, and storing its data check.
    assert len(timezone_utc_calls) == 3
