import logging
from datetime import datetime, timezone
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db, security_manager
from superset.connectors.sqla.models import SqlaTable

from ....api_support import second_reviewer_required, user_names
from ....common.exceptions import SemanticLayerError
from ....common.utils.type_formatter import iso_datetime
from ....core.database import (
    active_users,
    datasets_on_database,
    ensure_dictionary_tables,
    get_dataset,
    handle_errors,
    require_dataset,
    rollback_on_error,
)
from ....core.exceptions import DatabaseIdRequiredError, RequestBodyError
from ....core.security import csrf_protected, is_admin, is_superset_access_error, require_admin, require_dataset_access
from ...agent_ladder.services.agent_ladder import AGENT_ORIGIN
from ...data_dictionary.dependencies import column_dictionary_repository
from ..dependencies import (
    metric_contract_event_repository,
    metric_contract_repository,
    metric_definition_repository,
)
from ..exceptions import (
    ApprovedContractExistsError,
    ApprovedMetricContractRequiredError,
    MetricContractNotFoundError,
    MetricContractValidationError,
    MetricExecutionDeniedError,
    MetricNotFoundError,
    MetricSelfApprovalError,
)
from ..models import MetricContract, MetricContractEvent, MetricDefinition
from ..services.compiler import compile_semantic_query
from ..services.contracts import (
    build_preview_contract,
    contract_is_approved_current,
    execute_approved_chart_query,
    metric_contract_hash,
    metric_contract_ineligibility,
    metric_contract_state,
    parse_contract_metric,
)
from ..services.limits import (
    METRIC_DEFINITION_MAX_LENGTH,
    METRIC_REVIEW_REASON_MAX_LENGTH,
    METRIC_UNIT_MAX_LENGTH,
    semantic_query_row_cap,
)

logger = logging.getLogger(__name__)


class MetricContractRoutes:
    """Routes of SemanticLayerAPI. Metric contracts: their review, business definitions, history and execution."""

    @staticmethod
    def _dataset_metric(dataset: SqlaTable, metric_id: int):
        """Resolve only a metric actually attached to this dataset."""
        return next((metric for metric in dataset.metrics if metric.id == metric_id), None)

    @staticmethod
    def _contract_for(dataset_id: int, metric_id: int):
        return metric_contract_repository().for_dataset_metric(dataset_id, metric_id)

    @staticmethod
    def _serialize_metric_contract(contract: MetricContract, dataset: SqlaTable, metric: Any) -> dict[str, Any]:
        """Do not expose expression/hash in execution-facing responses."""
        return {
            "id": contract.id,
            "dataset_id": contract.dataset_id,
            "metric_id": contract.metric_id,
            "metric_name": metric.metric_name,
            "status": contract.status,
            "origin": contract.origin or "manual",
            "owner_id": contract.owner_id,
            "approver_id": contract.approver_id,
            "approved_at": iso_datetime(contract.approved_at),
            "revoker_id": contract.revoker_id,
            "revoked_at": iso_datetime(contract.revoked_at),
            "current": contract_is_approved_current(contract, dataset, metric),
        }

    @staticmethod
    def _active_users() -> list[dict[str, Any]]:
        """Active Superset users an administrator can name as a metric's steward."""
        return [{"id": user.id, "name": user.get_full_name().strip() or user.username} for user in active_users()]

    @staticmethod
    def _metric_definition(dataset_id: int, metric_id: int) -> MetricDefinition | None:
        return metric_definition_repository().for_dataset_metric(dataset_id, metric_id)

    @staticmethod
    def _serialize_metric_definition(definition: MetricDefinition | None, user_name: Any) -> dict[str, Any] | None:
        if definition is None:
            return None
        return {
            "business_definition": definition.business_definition,
            "unit": definition.unit,
            "steward_id": definition.steward_id,
            "steward_name": user_name(definition.steward_id),
        }

    @staticmethod
    def _review_reason() -> str | None:
        """The optional note or reason a reviewer sends with a metric decision, trimmed; blank means none."""
        body = request.get_json(silent=True)
        reason = body.get("reason") if isinstance(body, dict) else None
        if reason is None:
            return None
        if not isinstance(reason, str) or len(reason) > METRIC_REVIEW_REASON_MAX_LENGTH:
            limit = METRIC_REVIEW_REASON_MAX_LENGTH
            raise MetricContractValidationError(f"Lý do phải là văn bản tối đa {limit} ký tự.")
        return reason.strip() or None

    @staticmethod
    def _record_metric_event(
        dataset_id: int, metric_id: int, action: str, reason: str | None = None, contract: Any = None
    ) -> None:
        """Append one review event. Callers hash the metric first: adding a row can autoflush the session."""
        event = MetricContractEvent(
            dataset_id=dataset_id,
            metric_id=metric_id,
            action=action,
            actor_id=current_user.id,
            reason=reason,
            expression=contract.expression if contract is not None else None,
            expression_hash=contract.expression_hash if contract is not None else None,
            created_at=datetime.now(tz=timezone.utc),
        )
        metric_contract_event_repository().add(event, flush=False)

    @staticmethod
    def _query_dataset(dataset: SqlaTable) -> dict[str, Any]:
        """A dataset with the columns a metric run may group or filter by: active, physical and flagged in Superset."""
        query_columns = [
            {
                "column_name": column.column_name,
                "verbose_name": column.verbose_name,
                "type": column.type,
                "is_dttm": bool(column.is_dttm),
                "groupby": column.groupby is True,
                "filterable": column.filterable is True,
            }
            for column in dataset.columns
            if column.is_active is True
            and not column.expression
            and (column.groupby is True or column.filterable is True)
        ]
        name = f"{dataset.schema}.{dataset.table_name}" if dataset.schema else dataset.table_name
        return {"id": dataset.id, "name": name, "columns": query_columns}

    @expose("/metric-contracts", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_metric_contracts(self):
        """Every saved metric of one database with its contract state, parsed formula and why it is ineligible."""
        require_admin()
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            raise DatabaseIdRequiredError()
        ensure_dictionary_tables()
        datasets = datasets_on_database(database_id).order_by(SqlaTable.table_name).all()
        dataset_ids = [dataset.id for dataset in datasets]
        contracts = {
            (contract.dataset_id, contract.metric_id): contract
            for contract in metric_contract_repository().for_datasets(dataset_ids)
        } if dataset_ids else {}
        definitions = {
            (definition.dataset_id, definition.metric_id): definition
            for definition in metric_definition_repository().for_datasets(dataset_ids)
        } if dataset_ids else {}
        user_name = user_names()
        metrics = []
        for dataset in datasets:
            for metric in dataset.metrics:
                # Every Superset dataset gets a default COUNT(*) metric; it measures no column, so it is left out.
                if metric.metric_name == "count" or str(metric.expression or "").replace(" ", "").upper() == "COUNT(*)":
                    continue
                contract = contracts.get((dataset.id, metric.id))
                formula = parse_contract_metric(str(metric.expression or ""))
                metrics.append(
                    {
                        "dataset_id": dataset.id,
                        "metric_id": metric.id,
                        "metric_name": metric.metric_name,
                        "verbose_name": metric.verbose_name,
                        "description": metric.description,
                        "expression": metric.expression,
                        "d3format": metric.d3format,
                        "formula": formula.as_dict() if formula else None,
                        "ineligibility": metric_contract_ineligibility(dataset, metric),
                        "state": metric_contract_state(contract, dataset, metric),
                        "contract": {
                            **self._serialize_metric_contract(contract, dataset, metric),
                            "owner_name": user_name(contract.owner_id),
                            "approver_name": user_name(contract.approver_id),
                            "revoker_name": user_name(contract.revoker_id),
                        } if contract else None,
                        "definition": self._serialize_metric_definition(
                            definitions.get((dataset.id, metric.id)), user_name
                        ),
                    }
                )
        return self.response(
            200,
            datasets=[self._query_dataset(dataset) for dataset in datasets],
            metrics=metrics,
            users=self._active_users(),
            current_user_id=current_user.id,
            require_second_reviewer=second_reviewer_required(),
        )

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/candidate", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_metric_contract_candidate(self, dataset_id: int, metric_id: int):
        """Snapshot a saved metric for an administrator to review."""
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        metric = self._dataset_metric(dataset, metric_id)
        if metric is None:
            raise MetricNotFoundError()
        if ineligibility := metric_contract_ineligibility(dataset, metric):
            raise MetricContractValidationError(ineligibility)
        note = self._review_reason()
        # The AI Agent answers with this definition, so a metric must say what it means before anyone reviews it.
        if self._metric_definition(dataset_id, metric_id) is None:
            raise MetricContractValidationError("Nhập định nghĩa nghiệp vụ trước khi đề xuất metric.")
        contract = self._contract_for(dataset_id, metric_id)
        approved = contract is not None and contract.status == "approved"
        if approved and contract_is_approved_current(contract, dataset, metric):
            raise ApprovedContractExistsError()
        # Hashing lazy-loads the dataset's database, which autoflushes the session, so it must run before a new
        # contract joins the session: a pending contract without its hash would be flushed and break NOT NULL.
        expression_hash = metric_contract_hash(dataset, metric)
        if contract is None:
            contract = MetricContract(dataset_id=dataset_id, metric_id=metric_id, owner_id=current_user.id)
        # Whoever proposes this candidate owns it, even when an earlier proposal came from someone else.
        contract.owner_id = current_user.id
        # An administrator who proposes it again takes it over, so it no longer answers as an AI Agent figure.
        contract.origin = "manual"
        contract.metric_name = metric.metric_name
        contract.expression = metric.expression
        contract.expression_hash = expression_hash
        metric_contract_repository().add(contract, flush=False)
        contract.status = "candidate"
        contract.approver_id = None
        contract.approved_at = None
        contract.revoker_id = None
        contract.revoked_at = None
        self._record_metric_event(dataset_id, metric_id, "candidate", note, contract)
        db.session.commit()
        return self.response(201, contract=self._serialize_metric_contract(contract, dataset, metric))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve_metric_contract(self, dataset_id: int, metric_id: int):
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        metric = self._dataset_metric(dataset, metric_id)
        contract = self._contract_for(dataset_id, metric_id) if metric else None
        if metric is None or contract is None:
            raise MetricContractNotFoundError()
        if contract.status != "candidate":
            raise MetricContractValidationError("Only a candidate metric contract can be approved.")
        proposed_by_viewer = contract.owner_id is not None and contract.owner_id == current_user.id
        if proposed_by_viewer and second_reviewer_required():
            raise MetricSelfApprovalError()
        if ineligibility := metric_contract_ineligibility(dataset, metric):
            raise MetricContractValidationError(ineligibility)
        if contract.expression_hash != metric_contract_hash(dataset, metric):
            raise MetricContractValidationError("Metric changed; create a new candidate before approval.")
        note = self._review_reason()
        contract.status = "approved"
        contract.approver_id = current_user.id
        contract.approved_at = datetime.now(tz=timezone.utc)
        self._record_metric_event(dataset_id, metric_id, "approve", note, contract)
        db.session.commit()
        return self.response(200, contract=self._serialize_metric_contract(contract, dataset, metric))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke_metric_contract(self, dataset_id: int, metric_id: int):
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        metric = self._dataset_metric(dataset, metric_id)
        contract = self._contract_for(dataset_id, metric_id) if metric else None
        if metric is None or contract is None:
            raise MetricContractNotFoundError()
        if contract.status == "revoked":
            raise MetricContractValidationError("Metric này đã bị thu hồi.")
        reason = self._review_reason()
        if reason is None:
            raise MetricContractValidationError("Nhập lý do thu hồi.")
        contract.status = "revoked"
        contract.revoker_id = current_user.id
        contract.revoked_at = datetime.now(tz=timezone.utc)
        self._record_metric_event(dataset_id, metric_id, "revoke", reason, contract)
        db.session.commit()
        return self.response(200, contract=self._serialize_metric_contract(contract, dataset, metric))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/definition", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def save_metric_definition(self, dataset_id: int, metric_id: int):
        """Save a metric's business definition, unit and steward, and log the edit in its review history."""
        require_admin()
        ensure_dictionary_tables()
        dataset = get_dataset(dataset_id)
        metric = self._dataset_metric(dataset, metric_id) if dataset else None
        if metric is None:
            raise MetricNotFoundError()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise MetricContractValidationError("A JSON object is required.")
        business_definition = body.get("business_definition")
        unit, steward_id = body.get("unit"), body.get("steward_id")
        if not isinstance(business_definition, str) or not business_definition.strip():
            raise MetricContractValidationError("Định nghĩa nghiệp vụ không được để trống.")
        if len(business_definition) > METRIC_DEFINITION_MAX_LENGTH:
            raise MetricContractValidationError(f"Định nghĩa nghiệp vụ tối đa {METRIC_DEFINITION_MAX_LENGTH} ký tự.")
        if unit is not None and (not isinstance(unit, str) or len(unit) > METRIC_UNIT_MAX_LENGTH):
            raise MetricContractValidationError(f"Đơn vị phải là văn bản tối đa {METRIC_UNIT_MAX_LENGTH} ký tự.")
        valid_steward_id = isinstance(steward_id, int) and not isinstance(steward_id, bool)
        if steward_id is not None and (not valid_steward_id or security_manager.get_user_by_id(steward_id) is None):
            raise MetricContractValidationError("Người phụ trách không tồn tại.")
        definition = self._metric_definition(dataset_id, metric_id)
        if definition is None:
            definition = MetricDefinition(dataset_id=dataset_id, metric_id=metric_id)
        definition.business_definition = business_definition.strip()
        definition.unit = (unit or "").strip() or None
        definition.steward_id = steward_id
        metric_definition_repository().add(definition, flush=False)
        self._record_metric_event(dataset_id, metric_id, "definition")
        db.session.commit()
        return self.response(200, definition=self._serialize_metric_definition(definition, user_names()))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/events", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_metric_contract_events(self, dataset_id: int, metric_id: int):
        """A metric's review history, newest first."""
        require_admin()
        ensure_dictionary_tables()
        events = metric_contract_event_repository().history(dataset_id, metric_id)
        user_name = user_names()
        return self.response(
            200,
            events=[
                {
                    "id": event.id,
                    "action": event.action,
                    "actor_id": event.actor_id,
                    "actor_name": user_name(event.actor_id),
                    "reason": event.reason,
                    "expression": event.expression,
                    "created_at": iso_datetime(event.created_at),
                }
                for event in events
            ],
        )

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/semantic-query/execute", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def execute_metric_contract(self, dataset_id: int, metric_id: int):
        """Run a current approved metric, or let an administrator preview a candidate, through Superset ChartData."""
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        require_dataset_access(dataset)
        metric = self._dataset_metric(dataset, metric_id)
        contract = self._contract_for(dataset_id, metric_id) if metric else None
        if metric is None:
            raise ApprovedMetricContractRequiredError()
        body = request.get_json(silent=True)
        try:
            # validate() is Superset's datasource/RLS permission gate and runs as
            # the request's current_user; this route never compiles or runs SQL.
            from superset.charts.schemas import ChartDataQueryContextSchema
            from superset.commands.chart.data.get_data_command import ChartDataCommand

            def run_chart(payload):
                command = ChartDataCommand(ChartDataQueryContextSchema().load(payload))
                command.validate()
                return command.run()["queries"][0]

            # Administrators may preview a candidate so a reviewer sees real numbers before approving it; a candidate
            # the AI Agent built answers anyone as a provisional figure until it is approved or revoked.
            provisional = getattr(contract, "origin", None) == AGENT_ORIGIN
            result = execute_approved_chart_query(
                contract,
                dataset,
                metric,
                body,
                semantic_query_row_cap(),
                run_chart,
                allow_candidate=is_admin() or provisional,
            )
        except SemanticLayerError:
            raise
        except ValueError as ex:
            db.session.rollback()
            return self.response_400(message=str(ex))
        except Exception as ex:
            db.session.rollback()
            if is_superset_access_error(ex):
                raise MetricExecutionDeniedError() from ex
            logger.exception("Superset ChartData metric execution failed")
            return self.response_500(message="Metric execution was rejected by Superset.")
        if result.get("error"):
            return self.response_500(message="Metric execution failed.")
        rows = result.get("data", [])
        return self.response(
            200,
            columns=result.get("colnames", []),
            rows=rows[: semantic_query_row_cap()],
            row_count=min(len(rows), semantic_query_row_cap()),
            truncated=len(rows) > semantic_query_row_cap(),
            # The SQL Superset ran, RLS predicates included, so only administrators see it.
            sql=result.get("query") if is_admin() else None,
            preview=contract is not None and contract.status == "candidate",
        )

    @expose("/dataset/<int:dataset_id>/semantic-query/preview", methods=("POST",))
    @protect()
    @permission_name("read")
    @csrf_protected
    @handle_errors
    def preview_semantic_query(self, dataset_id: int):
        """Compile, but never execute, a one-dataset semantic query preview."""
        require_admin()
        dataset = require_dataset(dataset_id)
        require_dataset_access(dataset)
        query_request = request.get_json(silent=True)
        if not isinstance(query_request, dict):
            raise RequestBodyError()

        dictionary_columns = column_dictionary_repository().in_dataset(dataset_id).all()
        contract = build_preview_contract(dataset, dictionary_columns)
        preview = compile_semantic_query(
            contract["dataset"],
            [{**metric, "approved": metric["eligible_for_preview"]} for metric in contract["metrics"]],
            [{**dimension, "approved": dimension["eligible_for_preview"]} for dimension in contract["dimensions"]],
            query_request,
        )
        preview["provenance"]["contract_source"] = contract["contract_source"]
        preview["provenance"]["execution"] = "not_executed"
        return self.response(200, preview=preview)
