import logging
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset import security_manager
from superset.connectors.sqla.models import SqlaTable

from ....api_support import user_names
from ....core.database import (
    ensure_dictionary_tables,
    get_datasets,
    handle_errors,
    require_database,
    require_dataset,
    seed_dictionary,
)
from ....core.exceptions import DatabaseIdRequiredError
from ....core.security import can_access_dataset, is_superset_access_error, require_dataset_access
from ...agent_ladder.services.agent_ladder import AGGREGATE_DATASET
from ...business_model.dependencies import data_layer_repository
from ...data_dictionary.dependencies import (
    column_dictionary_repository,
    dataset_dictionary_repository,
    dataset_grain_repository,
)
from ...data_dictionary.models import ColumnDictionary
from ...data_dictionary.services.indicators import stored_indicator_model
from ..dependencies import metric_contract_repository, metric_definition_repository, relationship_contract_repository
from ..exceptions import ApprovedMetricDatasetRequiredError
from ..services.catalog import build_semantic_catalog
from ..services.dimension_labels import label_dimensions
from ..services.limits import semantic_query_row_cap
from ..services.members import (
    build_members_payload,
    build_time_range_payload,
    build_values_payload,
    coded_value_columns,
    coded_values_from_rows,
    labelled_key_columns,
    members_from_rows,
    temporal_columns,
    time_ranges_from_rows,
)
from ..services.relationships import relationship_is_approved_current
from ..services.schema_graph import GRAPH_VERSION, graph_edges, table_node

logger = logging.getLogger(__name__)


class ConsumerRoutes:
    """SemanticLayerAPI routes the AI Agent reads: the semantic catalog, dimension members and the schema graph."""

    @expose("/dataset/<int:dataset_id>/dimension-members", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def dimension_members(self, dataset_id: int):
        """Key and label pairs of the dataset's labelled key columns, for filtering a metric by a name.

        Only a dataset with an approved metric, or an aggregate dataset the AI Agent may build a metric on, is served;
        the pairs are read through Superset ChartData as the caller.
        """
        dataset = require_dataset(dataset_id)
        require_dataset_access(dataset)
        approved = metric_contract_repository().first_approved_on(dataset_id)
        dictionary = dataset_dictionary_repository().get(dataset_id) if approved is None else None
        if approved is None and getattr(dictionary, "dataset_type", None) != AGGREGATE_DATASET:
            raise ApprovedMetricDatasetRequiredError()
        from superset.charts.schemas import ChartDataQueryContextSchema
        from superset.commands.chart.data.get_data_command import ChartDataCommand

        dimensions = []
        for key_column, label_column in labelled_key_columns(dataset):
            try:
                command = ChartDataCommand(
                    ChartDataQueryContextSchema().load(build_members_payload(dataset, key_column, label_column))
                )
                command.validate()
                result = command.run()["queries"][0]
            except Exception as ex:
                if is_superset_access_error(ex):
                    continue
                logger.exception("Reading the members of %s.%s failed", dataset.table_name, label_column)
                continue
            if result.get("error"):
                continue
            label = next(
                (column.verbose_name for column in dataset.columns if column.column_name == label_column),
                None,
            )
            dimensions.append(
                {
                    "key_column": key_column,
                    "label_column": label_column,
                    "label": label or label_column,
                    "members": members_from_rows(result.get("data", []), key_column, label_column),
                }
            )
        return self.response(200, dataset_id=dataset_id, dimensions=dimensions, time_ranges=self._time_ranges(dataset))

    @staticmethod
    def _time_ranges(dataset: SqlaTable) -> list[dict[str, Any]]:
        """The first and last date of each date column, read through ChartData as the caller; empty when unreadable."""
        from superset.charts.schemas import ChartDataQueryContextSchema
        from superset.commands.chart.data.get_data_command import ChartDataCommand

        columns = temporal_columns(dataset)
        if not columns:
            return []
        try:
            command = ChartDataCommand(ChartDataQueryContextSchema().load(build_time_range_payload(dataset, columns)))
            command.validate()
            result = command.run()["queries"][0]
        except Exception as ex:
            if not is_superset_access_error(ex):
                logger.exception("Reading the date range of %s failed", dataset.table_name)
            return []
        return [] if result.get("error") else time_ranges_from_rows(result.get("data", []), columns)

    @staticmethod
    def _coded_values(dataset: SqlaTable, entries: dict[str, ColumnDictionary]) -> dict[str, list[str]]:
        """The stored values of each code column, read through ChartData as the caller; free text is left out."""
        from superset.charts.schemas import ChartDataQueryContextSchema
        from superset.commands.chart.data.get_data_command import ChartDataCommand

        columns = coded_value_columns(dataset, entries)
        if not columns:
            return {}
        try:
            command = ChartDataCommand(ChartDataQueryContextSchema().load(build_values_payload(dataset, columns)))
            command.validate()
            results = command.run()["queries"]
        except Exception as ex:
            if not is_superset_access_error(ex):
                logger.exception("Reading the coded values of %s failed", dataset.table_name)
            return {}
        coded = {}
        for name, result in zip(columns, results):
            values = None if result.get("error") else coded_values_from_rows(result.get("data", []), name)
            if values:
                coded[name] = values
        return coded

    @expose("/semantic-catalog", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def semantic_catalog(self):
        """List current approved semantic metadata filtered by caller datasource access."""
        ensure_dictionary_tables()
        metric_contracts = metric_contract_repository().approved()
        relationship_contracts = relationship_contract_repository().approved()
        dataset_ids = {contract.dataset_id for contract in metric_contracts}
        dataset_ids.update(contract.from_dataset_id for contract in relationship_contracts)
        dataset_ids.update(contract.to_dataset_id for contract in relationship_contracts)
        datasets = (
            {dataset.id: dataset for dataset in get_datasets(dataset_ids)}
            if dataset_ids
            else {}
        )
        relationships = []
        column_repository = column_dictionary_repository()
        for contract in relationship_contracts:
            entry = column_repository.get_for_dataset_column(contract.from_dataset_id, contract.from_column)
            if entry is None:
                continue
            ends = self._relationship_ends(entry)
            if ends is not None:
                relationships.append((contract, *ends))
        catalog = build_semantic_catalog(
            datasets,
            metric_contracts,
            relationships,
            can_access_dataset,
            semantic_query_row_cap(),
            self._catalog_metric_details(set(datasets)),
        )
        label_dimensions(catalog["datasets"])
        return self.response(200, **catalog)

    @staticmethod
    def _has_row_level_security(dataset: SqlaTable) -> bool:
        """Whether a row-level security rule applies to the caller on this dataset; unreadable counts as yes."""
        try:
            return bool(security_manager.get_rls_filters(dataset))
        except Exception:
            logger.warning("Reading the RLS rules of %s failed", dataset.table_name, exc_info=True)
            return True

    @expose("/schema-graph", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def schema_graph(self):
        """The base tables of a database the caller may read in full, and the approved relationships between them.

        This is what the AI Agent's schema link searches for join paths, as the caller: a table the caller may not
        read, or one a row-level security rule applies to, is no node, and its relationships are no edges.
        """
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            raise DatabaseIdRequiredError()
        ensure_dictionary_tables()
        database = require_database(database_id)
        nodes, excluded = [], []
        for dataset in self._base_tables(database_id):
            if not can_access_dataset(dataset):
                continue
            if self._has_row_level_security(dataset):
                excluded.append({"dataset_id": dataset.id, "table": dataset.table_name, "reason": "row_level_security"})
                continue
            nodes.append(self._schema_graph_node(dataset))
        node_ids = {node["dataset_id"] for node in nodes}
        approved = relationship_contract_repository().approved_between(node_ids) if node_ids else []
        column_repository = column_dictionary_repository()
        current = []
        for contract in approved:
            entry = column_repository.get_for_dataset_column(contract.from_dataset_id, contract.from_column)
            ends = self._relationship_ends(entry) if entry is not None else None
            if ends and relationship_is_approved_current(contract, *ends):
                current.append(contract)
        return self.response(
            200,
            version=GRAPH_VERSION,
            database={"id": database.id, "name": database.database_name, "dialect": database.backend},
            tables=nodes,
            edges=graph_edges(current),
            excluded=excluded,
        )

    def _schema_graph_node(self, dataset: SqlaTable) -> dict[str, Any]:
        seed_dictionary(dataset)
        dictionary = dataset_dictionary_repository().get(dataset.id)
        entries = {row.column_name: row for row in column_dictionary_repository().list_for_dataset(dataset.id)}
        grains = dataset_grain_repository().by_row_kind(dataset.id).all()
        model = stored_indicator_model(getattr(dictionary, "indicator_model", None))
        indicators = None
        if model and model["kind"] == "catalog":
            try:
                indicators = self._read_indicators(dataset, model)
            except Exception:
                # The graph still serves the table; linking then cannot name its indicators.
                logger.exception("Reading the indicators of %s for the schema graph failed", dataset.table_name)
        layer = data_layer_repository().get(dictionary.layer_id) if dictionary and dictionary.layer_id else None
        coded_values = self._coded_values(dataset, entries)
        return table_node(dataset, dictionary, entries, grains, coded_values, model, indicators, layer)

    def _catalog_metric_details(self, dataset_ids: set[int]) -> Any:
        """Business definition, unit, steward and discoverable glossary terms for each catalog metric."""
        definitions = (
            {
                (definition.dataset_id, definition.metric_id): definition
                for definition in metric_definition_repository().for_datasets(dataset_ids)
            }
            if dataset_ids
            else {}
        )
        terms_by_metric: dict[int, list[dict[str, Any]]] = {}
        for term in self._discoverable_glossary_terms():
            for link in term["links"]:
                if link["kind"] == "metric" and link["metric_id"] is not None:
                    terms_by_metric.setdefault(link["metric_id"], []).append(
                        {"term_id": term["term_id"], "name": term["canonical_name"], "synonyms": term["synonyms"]}
                    )
        user_name = user_names()

        def details(dataset_id: int, metric_id: int) -> dict[str, Any]:
            definition = definitions.get((dataset_id, metric_id))
            return {
                "business_definition": definition.business_definition if definition else None,
                "unit": definition.unit if definition else None,
                "steward_name": user_name(definition.steward_id) if definition else None,
                "glossary_terms": sorted(terms_by_metric.get(metric_id, []), key=lambda term: term["term_id"]),
            }

        return details
