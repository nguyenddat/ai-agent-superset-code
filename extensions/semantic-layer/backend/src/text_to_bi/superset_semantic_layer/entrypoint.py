"""Superset extension entrypoint for the semantic layer extension."""

from .modules.catalog.route import SemanticLayerAPI  # noqa: F401
from .modules.catalog.view import SemanticLayerView  # noqa: F401
