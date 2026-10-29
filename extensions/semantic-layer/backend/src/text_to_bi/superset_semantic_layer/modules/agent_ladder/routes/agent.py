import logging
from datetime import datetime, timezone
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset.connectors.sqla.models import SqlaTable, SqlMetric

from ....common.utils.type_formatter import iso_datetime
from ....core.database import handle_errors, rollback_on_error
from ....core.exceptions import DatasetIdRequiredError
from ....core.security import can_access_dataset, csrf_protected, require_admin, require_dataset_access
from ....migrations import ensure_dictionary_tables
from ...business_model.dependencies import lineage_edge_repository
from ...business_model.models import LineageEdge
from ...data_dictionary.dependencies import column_dictionary_repository, dataset_dictionary_repository
from ...data_dictionary.models import ColumnDictionary
from ...data_dictionary.services.seeding import seed_dictionary
from ...semantic_query.dependencies import metric_contract_repository, metric_definition_repository
from ...semantic_query.models import MetricContract, MetricDefinition
from ...semantic_query.services.chart_data import coded_values
from ...semantic_query.services.contracts import metric_contract_hash, metric_contract_state
from ...semantic_query.services.metric_review import (
    metric_contract_for,
    metric_definition_for,
    record_metric_event,
    review_reason,
)
from ...superset.services.datasets import get_datasets, is_internal_dataset, require_dataset
from ...superset.services.users import user_names
from ..dependencies import dataset_proposal_repository
from ..exceptions import (
    AgentLadderValidationError,
    AgentMetricPendingError,
    AgentMetricRevokedError,
    AggregateDatasetRequiredError,
    DatasetProposalNotFoundError,
    ProposalAlreadyReviewedError,
    ProposedDatasetCreationError,
    TooManyPendingAgentMetricsError,
    TooManyPendingProposalsError,
)
from ..models import DatasetProposal
from ..services.agent_ladder import (
    AGENT_DATASET_TYPES,
    AGENT_ORIGIN,
    AGGREGATE_DATASET,
    BASE_DATASET,
    MAX_PENDING_AGENT_METRICS,
    MAX_PENDING_PROPOSALS,
    asked_question,
    checked_dataset_proposal,
    checked_metric_draft,
    derived_column_keys,
    is_default_count,
    matching_metric,
    source_columns,
    source_metric,
    unique_metric_name,
)

logger = logging.getLogger(__name__)


class AgentLadderRoutes:
    """SemanticLayerAPI routes for the AI Agent's own metrics and dataset proposals."""

    @expose("/agent-sources", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def agent_sources(self):
        """Aggregate and base datasets the caller may query, described by the data dictionary.

        When no approved metric answers a question, the AI Agent builds a metric on an aggregate dataset, following the
        formulas already saved on it, or else drafts a dataset over base datasets, joined through their foreign keys.
        """
        ensure_dictionary_tables()
        dictionaries = {
            dictionary.id: dictionary
            for dictionary in dataset_dictionary_repository().of_types(AGENT_DATASET_TYPES)
        }
        datasets = (
            [
                dataset
                for dataset in get_datasets(list(dictionaries))
                if not is_internal_dataset(dataset) and can_access_dataset(dataset)
            ]
            if dictionaries
            else []
        )
        dataset_ids = [dataset.id for dataset in datasets]
        entries_by_dataset: dict[int, dict[str, ColumnDictionary]] = {}
        column_repository = column_dictionary_repository()
        for entry in column_repository.list_for_datasets(dataset_ids):
            entries_by_dataset.setdefault(entry.dataset_id, {})[entry.column_name] = entry
        target_ids = {
            entry.referenced_column
            for entries in entries_by_dataset.values()
            for entry in entries.values()
            if entry.referenced_column
        }
        referenced = (
            {
                entry.id: (entry.dataset_id, entry.column_name)
                for entry in column_repository.by_ids(list(target_ids)).all()
            }
            if target_ids
            else {}
        )
        contracts = (
            {
                (contract.dataset_id, contract.metric_id): contract
                for contract in metric_contract_repository().for_datasets(dataset_ids)
            }
            if dataset_ids
            else {}
        )
        definitions = (
            {
                (definition.dataset_id, definition.metric_id): definition
                for definition in metric_definition_repository().for_datasets(dataset_ids)
            }
            if dataset_ids
            else {}
        )
        described = []
        for dataset in sorted(datasets, key=lambda item: item.table_name):
            dictionary = dictionaries[dataset.id]
            aggregate = dictionary.dataset_type == AGGREGATE_DATASET
            entries = entries_by_dataset.get(dataset.id, {})
            described.append(
                {
                    "id": dataset.id,
                    "name": dataset.table_name,
                    "label": dictionary.display_name,
                    "dataset_type": dictionary.dataset_type,
                    "description": dictionary.description,
                    "grain": dictionary.grain,
                    "columns": source_columns(dataset, entries, referenced, coded_values(dataset, entries)),
                    "metrics": [
                        source_metric(
                            metric,
                            metric_contract_state(contracts.get((dataset.id, metric.id)), dataset, metric),
                            getattr(contracts.get((dataset.id, metric.id)), "origin", None),
                            definitions.get((dataset.id, metric.id)),
                        )
                        for metric in dataset.metrics
                        if not is_default_count(metric)
                    ]
                    if aggregate
                    else [],
                }
            )
        return self.response(200, datasets=described)

    @expose("/agent-metrics", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_agent_metric(self):
        """Save the metric the AI Agent built on an aggregate dataset as a candidate for review, or reuse one.

        A metric with the same formula already on the dataset is reused: an approved one answers as it is, one the agent
        proposed earlier answers as provisional again. A new metric gets its business definition and an AI Agent
        candidate contract, so it answers the asker at once as a provisional figure and waits for an administrator.
        """
        ensure_dictionary_tables()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise AgentLadderValidationError("A JSON object is required.")
        dataset_id = body.get("dataset_id")
        if not isinstance(dataset_id, int) or isinstance(dataset_id, bool):
            raise DatasetIdRequiredError()
        dataset = require_dataset(dataset_id)
        dictionary = dataset_dictionary_repository().get(dataset_id)
        if getattr(dictionary, "dataset_type", None) != AGGREGATE_DATASET or is_internal_dataset(dataset):
            raise AggregateDatasetRequiredError()
        require_dataset_access(dataset)
        draft = checked_metric_draft(body, dataset)
        question = asked_question(body)

        metric = matching_metric(dataset, draft.expression)
        contract = metric_contract_for(dataset_id, metric.id) if metric is not None else None
        if contract is not None:
            state = metric_contract_state(contract, dataset, metric)
            if state == "approved":
                return self.response(200, metric=self._agent_metric(dataset, metric), provisional=False)
            if state == "candidate" and contract.origin == AGENT_ORIGIN:
                return self.response(200, metric=self._agent_metric(dataset, metric), provisional=True)
            if state == "revoked":
                raise AgentMetricRevokedError()
            raise AgentMetricPendingError()
        if metric is None:
            pending = metric_contract_repository().count_on(dataset_id, origin=AGENT_ORIGIN, status="candidate")
            if pending >= MAX_PENDING_AGENT_METRICS:
                raise TooManyPendingAgentMetricsError()
            metric = SqlMetric(
                metric_name=unique_metric_name(dataset, draft.metric_name),
                verbose_name=draft.label,
                expression=draft.expression,
                description=draft.definition,
            )
            dataset.metrics.append(metric)
            db.session.flush()
        definition = metric_definition_for(dataset_id, metric.id)
        if definition is None:
            definition = MetricDefinition(
                dataset_id=dataset_id,
                metric_id=metric.id,
                business_definition=draft.definition,
                unit=draft.unit,
            )
            metric_definition_repository().add(definition, flush=False)
        # Hashing lazy-loads the dataset's database, which autoflushes, so it runs before the contract joins
        # the session.
        expression_hash = metric_contract_hash(dataset, metric)
        contract = MetricContract(
            dataset_id=dataset_id,
            metric_id=metric.id,
            metric_name=metric.metric_name,
            expression=metric.expression,
            expression_hash=expression_hash,
            status="candidate",
            origin=AGENT_ORIGIN,
            owner_id=current_user.id,
        )
        metric_contract_repository().add(contract, flush=False)
        note = f"AI Agent đề xuất khi trả lời: {question}" if question else "AI Agent đề xuất."
        record_metric_event(dataset_id, metric.id, "candidate", note, contract)
        db.session.commit()
        return self.response(201, metric=self._agent_metric(dataset, metric), provisional=True)

    def _agent_metric(self, dataset: SqlaTable, metric: Any) -> dict[str, Any]:
        """The metric in the shape of a semantic catalog metric, which the agent queries like an approved one."""
        definition = metric_definition_for(dataset.id, metric.id)
        return {
            "dataset_id": dataset.id,
            "metric_id": metric.id,
            "metric_name": metric.metric_name,
            "verbose_name": metric.verbose_name,
            "expression": metric.expression,
            "business_definition": getattr(definition, "business_definition", None) or metric.description,
            "unit": getattr(definition, "unit", None),
            "d3format": metric.d3format,
        }

    def _base_datasets(self, for_agent: bool) -> dict[str, SqlaTable]:
        """Base datasets by table name: those the caller may query for the agent, every one for an administrator."""
        base_ids = [row.id for row in dataset_dictionary_repository().of_type(BASE_DATASET)]
        datasets = get_datasets(base_ids)
        return {
            dataset.table_name: dataset
            for dataset in datasets
            if not is_internal_dataset(dataset) and (not for_agent or can_access_dataset(dataset))
        }

    def _serialize_dataset_proposal(self, proposal: DatasetProposal, user_name: Any) -> dict[str, Any]:
        sources = get_datasets(proposal.source_dataset_ids or [])
        return {
            "id": proposal.id,
            "name": proposal.name,
            "label": proposal.label,
            "description": proposal.description,
            "sql": proposal.sql,
            "metric": proposal.metric,
            "sources": [{"id": dataset.id, "name": dataset.table_name} for dataset in sources],
            "question": proposal.question,
            "status": proposal.status,
            "proposer_name": user_name(proposal.proposer_id),
            "created_on": iso_datetime(proposal.created_on),
            "reviewer_name": user_name(proposal.reviewer_id),
            "reviewed_on": iso_datetime(proposal.reviewed_on),
            "review_note": proposal.review_note,
            "dataset_id": proposal.dataset_id,
        }

    @expose("/agent-dataset-proposals", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def propose_agent_dataset(self):
        """Keep the dataset the AI Agent drafted over base datasets for an administrator; nothing runs until then.

        The same SQL already waiting for review is returned instead of a second proposal.
        """
        ensure_dictionary_tables()
        values = checked_dataset_proposal(request.get_json(silent=True), self._base_datasets(for_agent=True))
        user_name = user_names()
        proposal_repository = dataset_proposal_repository()
        waiting = proposal_repository.pending_with_fingerprint(values["sql_fingerprint"])
        if waiting is not None:
            return self.response(200, proposal=self._serialize_dataset_proposal(waiting, user_name))
        if proposal_repository.pending_count() >= MAX_PENDING_PROPOSALS:
            raise TooManyPendingProposalsError()
        proposal = DatasetProposal(
            **values,
            status="pending",
            proposer_id=current_user.id,
            created_on=datetime.now(tz=timezone.utc),
        )
        proposal_repository.add(proposal, flush=False)
        db.session.commit()
        return self.response(201, proposal=self._serialize_dataset_proposal(proposal, user_name))

    @expose("/dataset-proposals", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_dataset_proposals(self):
        """Every dataset the AI Agent proposed, waiting ones first, then newest first."""
        require_admin()
        ensure_dictionary_tables()
        proposals = dataset_proposal_repository().newest_first()
        proposals.sort(key=lambda proposal: proposal.status != "pending")
        user_name = user_names()
        return self.response(200, proposals=[self._serialize_dataset_proposal(item, user_name) for item in proposals])

    def _pending_proposal(self, proposal_id: int) -> DatasetProposal:
        require_admin()
        ensure_dictionary_tables()
        proposal = dataset_proposal_repository().get(proposal_id)
        if proposal is None:
            raise DatasetProposalNotFoundError()
        if proposal.status != "pending":
            raise ProposalAlreadyReviewedError()
        return proposal

    @expose("/dataset-proposals/<int:proposal_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_dataset_proposal(self, proposal_id: int):
        """Let an administrator correct the name, SQL or metric of a waiting proposal before creating it."""
        proposal = self._pending_proposal(proposal_id)
        body = request.get_json(silent=True)
        values = checked_dataset_proposal(
            {**body, "question": proposal.question} if isinstance(body, dict) else body,
            self._base_datasets(for_agent=False),
        )
        for attribute, value in values.items():
            setattr(proposal, attribute, value)
        db.session.commit()
        return self.response(200, proposal=self._serialize_dataset_proposal(proposal, user_names()))

    @expose("/dataset-proposals/<int:proposal_id>/reject", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def reject_dataset_proposal(self, proposal_id: int):
        proposal = self._pending_proposal(proposal_id)
        reason = review_reason(request.get_json(silent=True))
        if reason is None:
            raise AgentLadderValidationError("Nhập lý do từ chối.")
        proposal.status, proposal.review_note = "rejected", reason
        proposal.reviewer_id, proposal.reviewed_on = current_user.id, datetime.now(tz=timezone.utc)
        db.session.commit()
        return self.response(200, proposal=self._serialize_dataset_proposal(proposal, user_names()))

    @expose("/dataset-proposals/<int:proposal_id>/create", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_proposed_dataset(self, proposal_id: int):
        """Create the reviewed dataset in Superset and its metric as an AI Agent candidate.

        Superset reads the SQL's columns while creating the virtual dataset, so SQL that does not run is refused here.
        The dataset is an aggregate dataset in the data dictionary, so the agent builds further metrics on it.
        """
        proposal = self._pending_proposal(proposal_id)
        base_datasets = self._base_datasets(for_agent=False)
        values = checked_dataset_proposal(
            {
                "name": proposal.name,
                "label": proposal.label,
                "description": proposal.description,
                "sql": proposal.sql,
                "metric": proposal.metric,
                "question": proposal.question,
            },
            base_datasets,
        )
        from superset.commands.dataset.create import CreateDatasetCommand
        from superset.commands.dataset.exceptions import DatasetCreateFailedError, DatasetInvalidError

        try:
            dataset = CreateDatasetCommand(
                {
                    "database": values["database_id"],
                    "schema": values["schema"],
                    "table_name": values["name"],
                    "sql": values["sql"],
                    "owners": [current_user.id],
                }
            ).run()
        except DatasetInvalidError as ex:
            raise ProposedDatasetCreationError(f"Superset không tạo được dataset: {ex.normalized_messages()}") from ex
        except DatasetCreateFailedError as ex:
            logger.exception("Creating the proposed dataset %s failed", values["name"])
            raise ProposedDatasetCreationError() from ex
        seed_dictionary(dataset)
        dictionary = dataset_dictionary_repository().get(dataset.id)
        dictionary.display_name = values["label"]
        dictionary.description = values["description"]
        dictionary.dataset_type = AGGREGATE_DATASET
        self._carry_column_keys(dataset, values, base_datasets)
        metric_values = values["metric"]
        metric = SqlMetric(
            metric_name=metric_values["metric_name"],
            verbose_name=metric_values["label"],
            expression=metric_values["expression"],
            description=metric_values["definition"],
        )
        dataset.metrics.append(metric)
        db.session.flush()
        metric_definition_repository().add(
            MetricDefinition(
                dataset_id=dataset.id,
                metric_id=metric.id,
                business_definition=metric_values["definition"],
                unit=metric_values["unit"],
            ),
            flush=False,
        )
        expression_hash = metric_contract_hash(dataset, metric)
        contract = MetricContract(
            dataset_id=dataset.id,
            metric_id=metric.id,
            metric_name=metric.metric_name,
            expression=metric.expression,
            expression_hash=expression_hash,
            status="candidate",
            origin=AGENT_ORIGIN,
            owner_id=proposal.proposer_id,
        )
        metric_contract_repository().add(contract, flush=False)
        note = f"Tạo từ đề xuất dataset của AI Agent: {proposal.question or proposal.label}"
        record_metric_event(dataset.id, metric.id, "candidate", note, contract)
        proposal.status, proposal.dataset_id = "created", dataset.id
        proposal.reviewer_id, proposal.reviewed_on = current_user.id, datetime.now(tz=timezone.utc)
        db.session.commit()
        return self.response(200, proposal=self._serialize_dataset_proposal(proposal, user_names()))

    @staticmethod
    def _carry_column_keys(dataset: SqlaTable, values: dict[str, Any], base_datasets: dict[str, SqlaTable]) -> None:
        """Set PK, FK, unique and the referenced column on the new dataset's dictionary from the base columns it reads.

        Lineage is inferred from these references. A source that no output column references, because the query reads
        no key of it or its dictionary marks none, gets a manual flow edge into the new dataset instead, so the lineage
        diagram always shows where the dataset comes from.
        """
        sources = [dataset for dataset in base_datasets.values() if dataset.id in values["source_dataset_ids"]]
        entries: dict[int, dict[str, ColumnDictionary]] = {}
        column_repository = column_dictionary_repository()
        for entry in column_repository.list_for_datasets(values["source_dataset_ids"]):
            entries.setdefault(entry.dataset_id, {})[entry.column_name] = entry
        derived = derived_column_keys(values["sql"], sources, entries)
        for entry in column_repository.in_dataset(dataset.id):
            keys = derived.get(entry.column_name)
            if keys is None:
                continue
            referenced = entries[keys.referenced[0]][keys.referenced[1]]
            entry.is_pk, entry.is_unique = keys.is_pk, keys.is_unique
            entry.is_fk, entry.referenced_column = True, referenced.id
        referenced_sources = {keys.referenced[0] for keys in derived.values()}
        for source in sources:
            if source.id not in referenced_sources:
                edge = LineageEdge(source_dataset_id=source.id, target_dataset_id=dataset.id, kind="flow")
                lineage_edge_repository().add(edge, flush=False)
