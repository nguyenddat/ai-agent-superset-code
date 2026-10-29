import __future__

import ast
import copy
import importlib
import inspect
from collections.abc import Callable, Iterable
from functools import wraps
from pathlib import Path
from typing import Any, Generic, TypeVar

from sqlalchemy import select

from text_to_bi.superset_semantic_layer.common.utils import type_formatter

PACKAGE_PATH = Path(__file__).parents[1] / "src" / "text_to_bi" / "superset_semantic_layer"
MODULES_PATH = PACKAGE_PATH / "modules"
ROUTE_PATH = MODULES_PATH / "catalog" / "routes" / "semantic_layer.py"
# SemanticLayerAPI's route mixins live in each module's routes/; ExpertRuleAPI is a separate API.
ROUTE_PATHS = sorted(path for path in MODULES_PATH.glob("*/routes/*.py") if path.parts[-3] != "expert_rules")
# Superset's own datasets, databases and users, read through the superset module's repositories.
SUPERSET_SERVICE_PATHS = [MODULES_PATH / "superset" / "services" / name for name in ("datasets.py", "users.py")]
# The helpers those routes share, split out of the former catalog support module.
SHARED_SERVICE_PATHS = [
    MODULES_PATH / "data_dictionary" / "services" / "dictionary.py",
    MODULES_PATH / "business_model" / "services" / "layout.py",
    MODULES_PATH / "semantic_query" / "services" / "limits.py",
    MODULES_PATH / "semantic_query" / "services" / "dimension_labels.py",
    MODULES_PATH / "semantic_query" / "services" / "metric_review.py",
    MODULES_PATH / "semantic_query" / "services" / "relationship_lookup.py",
    MODULES_PATH / "semantic_query" / "services" / "chart_data.py",
    MODULES_PATH / "glossary" / "services" / "discovery.py",
    MODULES_PATH / "data_dictionary" / "services" / "seeding.py",
    *SUPERSET_SERVICE_PATHS,
]
CORE_PATHS = [PACKAGE_PATH / "core" / "security.py", PACKAGE_PATH / "core" / "database.py"]
FORMATTERS = [
    name
    for name, value in vars(type_formatter).items()
    if inspect.isfunction(value) and value.__module__ == type_formatter.__name__
]
SOURCE_PATHS = [PACKAGE_PATH / "migrations.py", *CORE_PATHS, *SHARED_SERVICE_PATHS, *ROUTE_PATHS]
DATASET_LOOKUPS = [
    "get_dataset", "get_datasets", "datasets_by_name", "datasets_on_database", "get_database",
    "active_users", "require_dataset", "require_database",
]
# The shared checks the routes call and the decorator that turns their errors into responses.
ROUTE_HELPERS = ["handle_errors", "require_admin", "require_dataset_access"]
# The exceptions are plain Python, so the routes raise the real ones.
EXCEPTION_MODULES = [
    "text_to_bi.superset_semantic_layer.common.exceptions",
    "text_to_bi.superset_semantic_layer.core.exceptions",
    *(
        f"text_to_bi.superset_semantic_layer.modules.{path.parent.name}.exceptions"
        for path in sorted(MODULES_PATH.glob("*/exceptions.py"))
    ),
]
DATA_ACCESS_PATHS = [
    PACKAGE_PATH / "common" / "base_repo.py",
    *sorted(path for path in MODULES_PATH.glob("*/repositories/*.py") if path.name != "__init__.py"),
    *sorted(MODULES_PATH.glob("*/dependencies.py")),
]
MODEL_NAMES = [
    name.value
    for path in MODULES_PATH.glob("*/models/__init__.py")
    for node in ast.parse(path.read_text(encoding="utf-8")).body
    if isinstance(node, ast.Assign) and node.targets[0].id == "__all__"
    for name in node.value.elts
]


def _trees() -> list[ast.Module]:
    return [ast.parse(path.read_text(encoding="utf-8")) for path in SOURCE_PATHS]


def api_methods() -> dict[str, ast.FunctionDef]:
    """Every method of SemanticLayerAPI and its route mixins, by name; each call returns fresh nodes."""
    return {
        member.name: member
        for tree in _trees()
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for member in node.body
        if isinstance(member, ast.FunctionDef)
    }


def module_function(name: str) -> ast.FunctionDef:
    """A module-level function of the routes, the shared services, core/security.py, core/database.py or migrations."""
    return next(
        node for tree in _trees() for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    )


def api_class(names: set[str], class_name: str = "SemanticLayerAPI") -> ast.ClassDef:
    """A class deriving from RestApi with the named methods, keeping only their @staticmethod and @handle_errors."""
    methods = api_methods()
    body = []
    for name in sorted(names):
        method = copy.deepcopy(methods[name])
        method.decorator_list = [
            item
            for item in method.decorator_list
            if isinstance(item, ast.Name) and item.id in {"staticmethod", "handle_errors"}
        ]
        body.append(method)
    return ast.ClassDef(
        name=class_name, bases=[ast.Name(id="RestApi", ctx=ast.Load())], keywords=[], body=body, decorator_list=[]
    )


def compile_into(namespace: dict, *nodes: ast.stmt) -> dict:
    """Run the given definitions in `namespace`, so they read its fakes as their globals."""
    namespace.setdefault("Any", Any)
    namespace.setdefault("Callable", Callable)
    # The formatters are pure, so the routes use the real ones.
    for name in FORMATTERS:
        namespace.setdefault(name, getattr(type_formatter, name))
    for module_name in EXCEPTION_MODULES:
        module = importlib.import_module(module_name)
        for name, value in vars(module).items():
            if isinstance(value, type) and issubclass(value, Exception):
                namespace.setdefault(name, value)
    namespace.setdefault("wraps", wraps)
    nodes = [module_function(name) for name in ROUTE_HELPERS if name not in namespace] + list(nodes)
    # The routes reach the database through core.database's dataset lookups and each module's repositories and
    # dependencies; their real code then runs on the test's fake db and fake models.
    if "db" in namespace:
        _compile_data_access(namespace)
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(ROUTE_PATH), "exec"), namespace)  # noqa: S102
    return namespace


def _compile_data_access(namespace: dict) -> None:
    namespace.setdefault("Iterable", Iterable)
    namespace.setdefault("Generic", Generic)
    namespace.setdefault("TypeVar", TypeVar)
    namespace.setdefault("select", select)
    for name in ["Model", "Query", "Session", "SqlaTable", "Database", *MODEL_NAMES]:
        namespace.setdefault(name, type(name, (), {}))
    database_functions = {
        node.name: node
        for path in SUPERSET_SERVICE_PATHS
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
    }
    missing = database_functions.keys() - namespace.keys()
    nodes = [database_functions[name] for name in DATASET_LOOKUPS if name in missing]
    for path in DATA_ACCESS_PATHS:
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                defined = [node.name]
            elif isinstance(node, ast.Assign):
                defined = [target.id for target in node.targets if isinstance(target, ast.Name)]
            else:
                continue
            if not any(name in namespace for name in defined):
                nodes.append(node)
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    # Annotations name real types the fakes do not provide, so they stay unevaluated.
    flags = __future__.annotations.compiler_flag
    exec(compile(module, "data_access", "exec", flags=flags, dont_inherit=True), namespace)  # noqa: S102
