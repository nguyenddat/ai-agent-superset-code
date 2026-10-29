from datetime import datetime, timezone
from typing import Any

from flask_login import current_user

from ..dependencies import metric_contract_event_repository, metric_contract_repository, metric_definition_repository
from ..exceptions import MetricContractValidationError
from ..models import MetricContract, MetricContractEvent, MetricDefinition
from .limits import METRIC_REVIEW_REASON_MAX_LENGTH


def metric_contract_for(dataset_id: int, metric_id: int) -> MetricContract | None:
    return metric_contract_repository().for_dataset_metric(dataset_id, metric_id)


def metric_definition_for(dataset_id: int, metric_id: int) -> MetricDefinition | None:
    return metric_definition_repository().for_dataset_metric(dataset_id, metric_id)


def review_reason(body: Any) -> str | None:
    """The optional note or reason a reviewer sends with a metric decision, trimmed; blank means none."""
    reason = body.get("reason") if isinstance(body, dict) else None
    if reason is None:
        return None
    if not isinstance(reason, str) or len(reason) > METRIC_REVIEW_REASON_MAX_LENGTH:
        limit = METRIC_REVIEW_REASON_MAX_LENGTH
        raise MetricContractValidationError(f"Lý do phải là văn bản tối đa {limit} ký tự.")
    return reason.strip() or None


def record_metric_event(
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
