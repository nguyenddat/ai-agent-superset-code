import json
import logging
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset import db

from ....common.utils.type_formatter import compact_json
from ....core.database import handle_errors, rollback_on_error
from ....core.exceptions import DatabaseIdRequiredError
from ....core.security import csrf_protected, require_admin
from ....migrations import ensure_dictionary_tables
from ...data_dictionary.dependencies import dataset_dictionary_repository
from ...superset.services.datasets import datasets_on_database, get_datasets, require_database
from ..dependencies import (
    business_canvas_repository,
    business_domain_repository,
    data_layer_repository,
    lineage_canvas_repository,
    lineage_edge_repository,
)
from ..exceptions import (
    BusinessDomainNotFoundError,
    BusinessModelValidationError,
    DataLayerNotFoundError,
    DuplicateBusinessDomainNameError,
    DuplicateDataLayerNameError,
)
from ..models import BusinessCanvas, BusinessDomain, DataLayer, LineageCanvas, LineageEdge
from ..services.business_model import (
    EDGE_KINDS,
    dataset_classifications,
    dataset_metrics,
    ensure_dataset_dictionaries,
    find_edge_override,
    infer_dictionary_edges,
    lineage_edges,
    serialize_domain,
    serialize_layer,
)
from ..services.layout import (
    CANVAS_DOMAIN_KEY,
    CANVAS_MAX_CELLS,
    CANVAS_MAX_COORDINATE,
    LINEAGE_EDGE_KEY,
    LINEAGE_EDGE_STYLES,
    LINEAGE_MAX_ITEMS,
    LINEAGE_MAX_POINTS,
    LINEAGE_NODE_KEY,
)

logger = logging.getLogger(__name__)


class BusinessModelRoutes:
    """SemanticLayerAPI routes for the Semantic Model: canvases, data layers, business domains and lineage edges."""

    @expose("/business-model", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_business_model(self):
        """Return business domains, dictionary-derived lineage and metrics for one Superset database."""
        require_admin()
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            raise DatabaseIdRequiredError()
        ensure_dictionary_tables()
        datasets = {
            dataset.id: dataset
            for dataset in datasets_on_database(database_id).all()
        }
        try:
            domains = business_domain_repository().by_name_order()
            layers = data_layer_repository().in_flow_order()
            canvas = business_canvas_repository().get(database_id)
            lineage_canvas = lineage_canvas_repository().get(database_id)
            return self.response(
                200,
                canvas=json.loads(canvas.layout) if canvas else None,
                lineage_canvas=json.loads(lineage_canvas.layout) if lineage_canvas else None,
                domains=[serialize_domain(domain, set(datasets)) for domain in domains],
                layers=[serialize_layer(layer) for layer in layers],
                classifications=dataset_classifications(list(datasets)),
                edges=lineage_edges(datasets),
                metrics=dataset_metrics(datasets),
            )
        except Exception:
            logger.exception("Could not load business model (database_id=%s)", database_id)
            db.session.rollback()
            return self.response_500(message="Could not load business model.")

    @staticmethod
    def _canvas_layout(payload: Any) -> dict[str, Any]:
        """Validate a business-view canvas: domain keys with their header and cells, and one cell per table."""

        def cell(value: Any) -> list[int]:
            if (
                not isinstance(value, list)
                or len(value) != 2
                or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
                or any(abs(item) > CANVAS_MAX_COORDINATE for item in value)
            ):
                raise BusinessModelValidationError("A cell must be a [col, row] pair of integers.")
            return [value[0], value[1]]

        if not isinstance(payload, dict):
            raise BusinessModelValidationError("Request body must be an object.")
        domains, tables = payload.get("domains"), payload.get("tables")
        if not isinstance(domains, list) or not isinstance(tables, dict):
            raise BusinessModelValidationError("domains must be a list and tables an object.")
        layout: dict[str, Any] = {"domains": [], "tables": {}}
        keys = set()
        for domain in domains:
            if not isinstance(domain, dict) or not CANVAS_DOMAIN_KEY.match(str(domain.get("key", ""))):
                raise BusinessModelValidationError("Each domain needs a key such as domain-1 or domain-unassigned.")
            if domain["key"] in keys:
                raise BusinessModelValidationError("Domain keys must be unique.")
            keys.add(domain["key"])
            cells = domain.get("cells")
            if not isinstance(cells, list) or not cells:
                raise BusinessModelValidationError("Each domain needs at least one cell.")
            layout["domains"].append(
                {"key": domain["key"], "header": cell(domain.get("header")), "cells": [cell(item) for item in cells]}
            )
        for dataset_id, position in tables.items():
            if not str(dataset_id).isdigit():
                raise BusinessModelValidationError("tables must be keyed by dataset ID.")
            layout["tables"][str(int(dataset_id))] = cell(position)
        if sum(len(domain["cells"]) for domain in layout["domains"]) + len(layout["tables"]) > CANVAS_MAX_CELLS:
            raise BusinessModelValidationError("The canvas has too many cells.")
        return layout

    @expose("/business-canvas", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def save_business_canvas(self):
        """Store where the business view draws each domain and table for one Superset database."""
        require_admin()
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            raise DatabaseIdRequiredError()
        ensure_dictionary_tables()
        require_database(database_id)
        layout = self._canvas_layout(request.get_json(silent=True))
        try:
            canvas_repository = business_canvas_repository()
            canvas = canvas_repository.get(database_id)
            if canvas is None:
                canvas = canvas_repository.add(BusinessCanvas(database_id=database_id), flush=False)
            canvas.layout = compact_json(layout)
            db.session.commit()
            return self.response(200, database_id=database_id)
        except Exception:
            logger.exception("Could not save business canvas (database_id=%s)", database_id)
            db.session.rollback()
            return self.response_500(message="Could not save business canvas.")

    @staticmethod
    def _lineage_layout(payload: Any) -> dict[str, Any]:
        """Validate a lineage canvas: card positions and edge shapes keyed by their canvas IDs."""

        def number(value: Any) -> float:
            if isinstance(value, bool) or not isinstance(value, int | float) or abs(value) > CANVAS_MAX_COORDINATE:
                raise BusinessModelValidationError("Coordinates must be numbers within the canvas.")
            return round(float(value), 1)

        def point(value: Any) -> list[float]:
            if not isinstance(value, list) or len(value) != 2:
                raise BusinessModelValidationError("A point must be an [x, y] pair.")
            return [number(value[0]), number(value[1])]

        def numbers(value: Any) -> list[float]:
            if not isinstance(value, list) or len(value) > LINEAGE_MAX_POINTS:
                raise BusinessModelValidationError(f"An edge holds at most {LINEAGE_MAX_POINTS} points.")
            return [number(item) for item in value]

        if not isinstance(payload, dict):
            raise BusinessModelValidationError("Request body must be an object.")
        nodes, edges = payload.get("nodes", {}), payload.get("edges", {})
        if not isinstance(nodes, dict) or not isinstance(edges, dict):
            raise BusinessModelValidationError("nodes and edges must be objects.")
        if len(nodes) + len(edges) > LINEAGE_MAX_ITEMS:
            raise BusinessModelValidationError("The lineage canvas has too many items.")
        layout: dict[str, Any] = {"nodes": {}, "edges": {}}
        for key, position in nodes.items():
            if not LINEAGE_NODE_KEY.match(str(key)):
                raise BusinessModelValidationError("nodes must be keyed by card IDs such as table-1 or metric-1.")
            layout["nodes"][key] = point(position)
        for key, shape in edges.items():
            if not LINEAGE_EDGE_KEY.match(str(key)) or not isinstance(shape, dict):
                raise BusinessModelValidationError("edges must be keyed by edge IDs such as flow-1-2 or metric-edge-1.")
            if shape.get("style") not in LINEAGE_EDGE_STYLES:
                raise BusinessModelValidationError("An edge style must be orthogonal, straight or curved.")
            waypoints = shape.get("waypoints", [])
            if not isinstance(waypoints, list) or len(waypoints) > LINEAGE_MAX_POINTS:
                raise BusinessModelValidationError(f"An edge holds at most {LINEAGE_MAX_POINTS} points.")
            label, ports = shape.get("label"), shape.get("ports", [0, 0])
            layout["edges"][key] = {
                "style": shape["style"],
                "coords": numbers(shape.get("coords", [])),
                "waypoints": [point(item) for item in waypoints],
                "label": None if label is None else point(label),
                "ports": point(ports),
            }
        return layout

    @expose("/lineage-canvas", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def save_lineage_canvas(self):
        """Store the lineage cards the user moved and the edges the user shaped for one Superset database."""
        require_admin()
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            raise DatabaseIdRequiredError()
        ensure_dictionary_tables()
        require_database(database_id)
        layout = self._lineage_layout(request.get_json(silent=True))
        try:
            canvas_repository = lineage_canvas_repository()
            canvas = canvas_repository.get(database_id)
            if canvas is None:
                canvas = canvas_repository.add(LineageCanvas(database_id=database_id), flush=False)
            canvas.layout = compact_json(layout)
            db.session.commit()
            return self.response(200, database_id=database_id)
        except Exception:
            logger.exception("Could not save lineage canvas (database_id=%s)", database_id)
            db.session.rollback()
            return self.response_500(message="Could not save lineage canvas.")

    @expose("/data-layers", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_data_layers(self):
        """List admin-defined data layers in flow order."""
        require_admin()
        ensure_dictionary_tables()
        layers = data_layer_repository().in_flow_order()
        return self.response(200, layers=[serialize_layer(layer) for layer in layers])

    @staticmethod
    def _layer_values(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise BusinessModelValidationError("Request body must be an object.")
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
            raise BusinessModelValidationError("name must be a non-empty string of at most 255 characters.")
        description = payload.get("description")
        if description is not None and not isinstance(description, str):
            raise BusinessModelValidationError("description must be a string or null.")
        color = payload.get("color")
        if color is not None and (not isinstance(color, str) or len(color) > 16):
            raise BusinessModelValidationError("color must be a string of at most 16 characters or null.")
        return {"name": name.strip(), "description": (description or "").strip() or None, "color": color or None}

    def _save_layer(self, layer: DataLayer | None):
        values = self._layer_values(request.get_json(silent=True))
        layer_repository = data_layer_repository()
        duplicate = layer_repository.by_name(values["name"])
        if duplicate is not None and (layer is None or duplicate.id != layer.id):
            raise DuplicateDataLayerNameError()
        if layer is None:
            # A new layer starts a level of its own after the existing ones; the levels order then places it.
            last = layer_repository.last_in_order()
            top = layer_repository.on_top_level()
            layer = DataLayer(sort_order=(last.sort_order + 1) if last else 0, level=(top.level + 1) if top else 0)
            layer_repository.add(layer, flush=False)
        for attribute, value in values.items():
            setattr(layer, attribute, value)
        db.session.commit()
        return self.response(200, layer=serialize_layer(layer))

    @expose("/data-layers", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_data_layer(self):
        """Append a data layer after the existing ones."""
        require_admin()
        ensure_dictionary_tables()
        return self._save_layer(None)

    @expose("/data-layers/<int:layer_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_data_layer(self, layer_id: int):
        """Rename or recolour a data layer."""
        require_admin()
        ensure_dictionary_tables()
        layer = data_layer_repository().get(layer_id)
        if layer is None:
            raise DataLayerNotFoundError()
        return self._save_layer(layer)

    @expose("/data-layers/<int:layer_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_data_layer(self, layer_id: int):
        """Delete a data layer; its datasets become unclassified."""
        require_admin()
        ensure_dictionary_tables()
        layer_repository = data_layer_repository()
        layer = layer_repository.get(layer_id)
        if layer is None:
            raise DataLayerNotFoundError()
        dataset_dictionary_repository().unclassify_layer(layer_id)
        layer_repository.delete(layer)
        db.session.commit()
        return self.response(200, id=layer_id)

    @expose("/data-layers/order", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def reorder_data_layers(self):
        """Set the levels of all data layers, in flow order, from a list of levels that each list their layer IDs."""
        require_admin()
        ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        levels = payload.get("levels") if isinstance(payload, dict) else None
        layers = {layer.id: layer for layer in data_layer_repository().all()}
        if not isinstance(levels, list) or not all(isinstance(level, list) and level for level in levels):
            raise BusinessModelValidationError("levels must be a list of non-empty lists of data layer IDs.")
        ids = [layer_id for level in levels for layer_id in level]
        if any(isinstance(layer_id, bool) or not isinstance(layer_id, int) for layer_id in ids) or sorted(
            ids
        ) != sorted(layers):
            raise BusinessModelValidationError("levels must list every data layer exactly once.")
        for level_index, level in enumerate(levels):
            for layer_id in level:
                layers[layer_id].level = level_index
        for position, layer_id in enumerate(ids):
            layers[layer_id].sort_order = position
        db.session.commit()
        return self.response(200, layers=[serialize_layer(layers[layer_id]) for layer_id in ids])

    @staticmethod
    def _domain_values(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise BusinessModelValidationError("Request body must be an object.")
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
            raise BusinessModelValidationError("name must be a non-empty string of at most 255 characters.")
        description = payload.get("description")
        if description is not None and not isinstance(description, str):
            raise BusinessModelValidationError("description must be a string or null.")
        color = payload.get("color")
        if color is not None and (not isinstance(color, str) or len(color) > 16):
            raise BusinessModelValidationError("color must be a string of at most 16 characters or null.")
        dataset_ids = payload.get("dataset_ids", [])
        if not isinstance(dataset_ids, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in dataset_ids):
            raise BusinessModelValidationError("dataset_ids must be a list of dataset IDs.")
        datasets = get_datasets(dataset_ids)
        if len(datasets) != len(set(dataset_ids)):
            raise BusinessModelValidationError("dataset_ids contains unknown datasets.")
        ensure_dataset_dictionaries(datasets)
        dictionaries = dataset_dictionary_repository().list_by_ids(dataset_ids)
        return {
            "name": name.strip(),
            "description": (description or "").strip() or None,
            "color": color or None,
            "datasets": dictionaries,
        }

    def _save_domain(self, domain: BusinessDomain | None):
        ensure_dictionary_tables()
        values = self._domain_values(request.get_json(silent=True))
        domain_repository = business_domain_repository()
        duplicate = domain_repository.by_name(values["name"])
        if duplicate is not None and (domain is None or duplicate.id != domain.id):
            raise DuplicateBusinessDomainNameError()
        try:
            if domain is None:
                domain = domain_repository.add(BusinessDomain(), flush=False)
            for attribute, value in values.items():
                setattr(domain, attribute, value)
            db.session.commit()
            return self.response(200, domain=serialize_domain(domain))
        except Exception:
            logger.exception("Could not save business domain")
            db.session.rollback()
            return self.response_500(message="Could not save business domain.")

    @expose("/business-domains", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_business_domain(self):
        """Create a business domain and assign datasets to it."""
        require_admin()
        return self._save_domain(None)

    @expose("/business-domains/<int:domain_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_business_domain(self, domain_id: int):
        """Rename a business domain or replace its datasets."""
        require_admin()
        ensure_dictionary_tables()
        domain = business_domain_repository().get(domain_id)
        if domain is None:
            raise BusinessDomainNotFoundError()
        return self._save_domain(domain)

    @expose("/business-domains/<int:domain_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_business_domain(self, domain_id: int):
        """Delete a business domain; its datasets are kept."""
        require_admin()
        ensure_dictionary_tables()
        domain_repository = business_domain_repository()
        domain = domain_repository.get(domain_id)
        if domain is None:
            raise BusinessDomainNotFoundError()
        domain_repository.delete(domain)
        db.session.commit()
        return self.response(200, id=domain_id)

    @staticmethod
    def _edge_key(payload: Any) -> tuple[int, int, str]:
        if not isinstance(payload, dict):
            raise BusinessModelValidationError("Request body must be an object.")
        source_id, target_id, kind = payload.get("source"), payload.get("target"), payload.get("kind")
        for value in (source_id, target_id):
            if isinstance(value, bool) or not isinstance(value, int):
                raise BusinessModelValidationError("source and target must be dataset IDs.")
        if source_id == target_id:
            raise BusinessModelValidationError("An edge cannot connect a dataset to itself.")
        if kind not in EDGE_KINDS:
            raise BusinessModelValidationError(f"kind must be one of: {', '.join(EDGE_KINDS)}.")
        datasets = get_datasets([source_id, target_id])
        if len(datasets) != 2:
            raise BusinessModelValidationError("Unknown source or target dataset.")
        ensure_dataset_dictionaries(datasets)
        return source_id, target_id, kind

    @staticmethod
    def _edge_override(key: tuple[int, int, str]) -> tuple[LineageEdge | None, bool]:
        """The override row for an edge and whether the data dictionary infers that edge."""
        datasets = {
            dataset.id: dataset for dataset in get_datasets(key[:2])
        }
        inferred = infer_dictionary_edges(datasets)
        return find_edge_override(key, inferred), key in inferred

    @expose("/lineage-edges", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def add_lineage_edge(self):
        """Add a manual lineage edge, or restore an inferred edge that was hidden."""
        require_admin()
        ensure_dictionary_tables()
        source_id, target_id, kind = self._edge_key(request.get_json(silent=True))
        edge, _ = self._edge_override((source_id, target_id, kind))

        if edge is None:
            lineage_edge_repository().add(
                LineageEdge(source_dataset_id=source_id, target_dataset_id=target_id, kind=kind), flush=False
            )
        elif edge.is_hidden:
            # Unhiding an inferred edge only needs the override removed.
            lineage_edge_repository().delete(edge)
        else:
            # A colour-only row for an inferred edge becomes a manual edge that outlives the FK declaration.
            edge.is_manual = True
        db.session.commit()
        return self.response(200, source=source_id, target=target_id, kind=kind)

    @expose("/lineage-edges/color", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def set_lineage_edge_color(self):
        """Set or clear the display colour of a lineage edge, whether manual or inferred from the dictionary."""
        require_admin()
        ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        source_id, target_id, kind = self._edge_key(payload)
        color = payload.get("color")
        if color is not None and (not isinstance(color, str) or not color.startswith("#") or len(color) > 16):
            raise BusinessModelValidationError("color must be a hex colour such as #2563eb, or null.")
        edge, _ = self._edge_override((source_id, target_id, kind))

        if edge is None:
            if color is not None:
                lineage_edge_repository().add(
                    LineageEdge(
                        source_dataset_id=source_id,
                        target_dataset_id=target_id,
                        kind=kind,
                        is_manual=False,
                        color=color,
                    ),
                    flush=False,
                )
        elif color is None and not edge.is_manual and not edge.is_hidden:
            lineage_edge_repository().delete(edge)
        else:
            edge.color = color
        db.session.commit()
        return self.response(200, source=source_id, target=target_id, kind=kind, color=color)

    @expose("/lineage-edges", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def remove_lineage_edge(self):
        """Remove a manual lineage edge, or hide an edge inferred from the data dictionary."""
        require_admin()
        ensure_dictionary_tables()
        source_id, target_id, kind = self._edge_key(request.get_json(silent=True))
        edge, inferred = self._edge_override((source_id, target_id, kind))

        if inferred:
            # The dictionary keeps producing this edge, so it is suppressed with a hidden override.
            if edge is None:
                lineage_edge_repository().add(
                    LineageEdge(source_dataset_id=source_id, target_dataset_id=target_id, kind=kind, is_hidden=True),
                    flush=False,
                )
            else:
                edge.is_hidden = True
        elif edge is not None:
            lineage_edge_repository().delete(edge)
        db.session.commit()
        return self.response(200, source=source_id, target=target_id, kind=kind)
