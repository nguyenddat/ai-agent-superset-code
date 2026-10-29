from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ..exceptions import ExpertRuleConflictError, ExpertRuleSelfApprovalError, ExpertRuleValidationError
from .sql_validation import contains_sql_or_control

MAX_NAME = 255
MAX_ITEMS = 50
MAX_TEXT = 2_000
MAX_REASON = 512
_URL = re.compile(r"\b(?:[a-z][a-z0-9+.-]*://|www\.)", re.IGNORECASE)
_SECRET = re.compile(
    r"\b(?:api[-_ ]?key|access[-_ ]?token|secret|password|passwd|authorization|bearer|credential)\b\s*(?:[:=]|\S)",
    re.IGNORECASE,
)
# These patterns deliberately require a statement-shaped construct at the
# beginning of the prose field.  A word such as ``update`` or ``show`` alone is
# ordinary language; coupled with SQL grammar it is executable syntax.
_SQL_STATEMENTS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*begin(?:\s+(?:transaction|work))?\b",
        r"^\s*start\s+transaction\b",
        r"^\s*(?:commit|rollback)\b",
        r"^\s*savepoint\b",
        r"^\s*set\s+(?:transaction|session)\b",
        r"^\s*lock\s+table\b",
        r"^\s*declare\s+\w+\b",
        r"^\s*do\s+(?:language\b|\$\$)",
        r"^\s*(?:exec(?:ute)?)\s+\S+",
        r"^\s*call\s+[\w.]+\s*\(",
        r"^\s*(?:deallocate|reset|discard)\s+all\s*$",
        r"^\s*(?:listen|notify)\s+\w+\b",
        r"^\s*reindex\s+(?:table|index)\b",
        r"^\s*(?:pragma|vacuum)\b",
        r"^\s*(?:copy\s+\S+|load\s+data\b)",
        r"^\s*(?:create|alter|drop|truncate)\s+(?:table|view|index|schema|database)\b",
        r"^\s*insert\s+into\b",
        r"^\s*update\s+\S+\s+set\b",
        r"^\s*delete\s+from\b",
        r"^\s*(?:merge|replace|upsert)\s+into\b",
        r"^\s*select\s+(?:\*|\d+\b|['\"]|[\w.]+\s*(?:\(|,|from\b|as\b|$))",
        r"^\s*with\s+(?:recursive\s+)?\w+\s+as\s*\(",
        r"^\s*values\s*\(",
        r"^\s*show\s+(?:databases|tables|schemas)\s*$",
        r"^\s*(?:describe|desc)\s+\w+\s*$",
        r"^\s*explain\s+(?:select|analyze)\b",
        r"^\s*analy[sz]e\s+\w+\s*$",
    )
)
# A SQL fragment can be prefaced by explanatory prose (for example, ``use
# SELECT * FROM ...``).  These sequences contain enough grammar to distinguish
# them from ordinary language such as ``Update the monthly report``.  Keep
# command-only controls in ``_SQL_STATEMENTS`` above: matching lone words such
# as ``show`` or ``set`` anywhere would recreate the old keyword denylist.
_SQL_GRAMMAR = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bwith\s+(?:recursive\s+)?[a-z_]\w*\s+as\s*\(",
        r"\bselect\s+(?:\*|\d+|(?:distinct\s+)?[\w.]+(?:\s*,\s*[\w.]+)*)\s+from\b",
        r"\bselect\s+[\w.\"]+\s*[+\-*/]\s*[\w.\"]+\s+from\s+[\w.\"]+\b",
        r"\bselect\s+[\w.\"]+\s*(?:\([^)]*\)|::\s*\w+)\s+from\b",
        # SELECT expressions do not need a FROM clause.  Restrict the signal
        # to unambiguously SQL-shaped expressions so prose such as "select a
        # monthly option" does not become a keyword false positive.
        r"\bselect\s+(?:distinct\s+)?[a-z_]\w*(?:\.[a-z_]\w*)?\s*\(",
        r"\bselect\s+cast\s*\(",
        r"\bselect\s+(?:current_user|current_role|current_catalog|current_schema|session_user)\b",
        r"\bselect\s+\d+\b",
        r"\binsert\s+into\s+[\w.\"]+\b",
        r"\bupdate\s+(?:only\s+)?[\w.\"]+\s+set\s+",
        r"\bdelete\s+from\s+[\w.\"]+\b",
        r"\b(?:merge|replace|upsert)\s+into\s+[\w.\"]+\b",
        r"\b(?:create|alter|drop)\s+(?:(?:temporary|temp|materialized|unique)\s+)*(?:table|view|index|schema|database)\s+[\w.\"]+\b",
        r"\bdrop\s+if\s+exists\s+(?:table|view|index|schema|database)\s+[\w.\"]+\b",
        r"\btruncate\s+(?:table\s+)?[\w.\"]+\b",
        r"\bcopy\s*\(\s*select\s+",
        r"\bvalues\s*\(",
        r"\bshow\s+(?:all|search_path|databases|tables|schemas)\b",
        r"\b(?:describe|desc)\s+[\w.\"]+\b",
        r"\bexplain\s+(?:analyze\s+)?select\s+",
        r"\banaly[sz]e\s+[\w.\"]+\b",
    )
)
# Transaction and session controls are executable statements even when a user
# buries them in an explanatory sentence.  Each expression needs a command
# sequence (rather than matching a lone common word such as ``set`` or ``do``),
# which keeps ordinary declarative prose valid while failing closed for SQL.
_SQL_CONTROLS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bbegin(?:\s+(?:transaction|work))?\b",
        r"\bstart\s+transaction\b",
        r"\b(?:commit|rollback)(?:\s+(?:transaction|work|now))?\b",
        r"\bsavepoint\s+[a-z_]\w*\b",
        r"\bset\s+(?:transaction|session)\b",
        r"\bset\s+role\s+[a-z_][\w$]*\b",
        r"\bset\s+search_path\s+(?:to|=)\s+[a-z_][\w$]*\b",
        r"\block\s+table\s+[\w.\"]+\b",
        r"\bdeclare\s+[a-z_]\w*\b",
        r"\bdo\s+language\s+[a-z_]\w*\b",
        r"\bexec(?:ute)?\s+[a-z_][\w.]*\b",
        r"\bcall\s+[a-z_][\w.]*\s*\(",
        r"\bpragma\s+[a-z_]\w*\b",
        r"\bvacuum\b",
        r"\bcopy\s+[\w.\"]+\b",
        r"\bload\s+(?:data\b|file\b)",
        r"\balter\s+system\s+set\s+[a-z_][\w.]*\b",
        r"\breindex\s+(?:table|index|database)\s+[\w.\"]+\b",
        r"\bdeallocate\s+(?:prepare\s+[a-z_]\w*|all)\b",
        r"\b(?:reset|discard)\s+all\b",
        r"\b(?:listen|notify)\s+[a-z_]\w*\b",
    )
)
_CONDITION_OPERATORS = frozenset(
    {
        "equals", "not_equals", "contains", "not_contains", "greater_than", "greater_than_or_equal",
        "less_than", "less_than_or_equal", "in", "not_in", "is_null", "is_not_null",
    }
)
_VALUE_TYPES = frozenset({"string", "number", "boolean", "null", "array"})


def _text(value: Any, field: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not (clean := " ".join(value.split())) or len(clean) > limit:
        raise ExpertRuleValidationError(f"Invalid {field}.")
    # Rule values are declarative prose, never a transport for executable SQL,
    # links, or credentials. URLs are rejected wholesale so query credentials
    # cannot be smuggled in through otherwise harmless-looking parameters.
    if _contains_executable_sql_syntax(clean) or _URL.search(clean) or _SECRET.search(clean):
        raise ExpertRuleValidationError(f"Unsafe {field}.")
    return clean


def _contains_executable_sql_syntax(value: str) -> bool:
    """Reject SQL lexical/control grammar while retaining ordinary prose.

    The fields are prose only, so SQL comments, separators, dollar quoting, and
    statement-shaped control syntax is never valid. Requiring its grammar,
    rather than globally denying words, avoids false positives such as
    ``Update the monthly report`` and ``beginning balance``.
    """
    return contains_sql_or_control(value)


def _contains_sql_grammar_candidate(value: str) -> bool:
    """Reject an unambiguous SQL grammar span embedded in declarative prose.

    This deliberately small, dependency-free grammar recognizer covers only
    statement/expression forms that cannot be ordinary prose.  It runs after
    lexical control checks, and every recognized candidate fails closed rather
    than relying on an optional SQL parser being present in the extension
    runtime.
    """
    for pattern in _SQL_GRAMMAR:
        if pattern.search(value):
            return True
    return False


def _reason(value: Any) -> str | None:
    """Normalize optional audit rationale before it can become immutable evidence."""
    if value is None:
        return None
    return _text(value, "reason", MAX_REASON)


def _id_list(value: Any, field: str) -> list[int]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ExpertRuleValidationError(f"Invalid {field}.")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ExpertRuleValidationError(f"Invalid {field}.")
    if len(set(value)) != len(value):
        raise ExpertRuleValidationError(f"Duplicate {field}.")
    return value


def _items(value: Any, field: str, keys: set[str], allow_empty: bool = False) -> list[dict[str, str]]:
    if not isinstance(value, list) or (not value and not allow_empty) or len(value) > MAX_ITEMS:
        raise ExpertRuleValidationError(f"Invalid {field}.")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != keys:
            raise ExpertRuleValidationError(f"Invalid {field}.")
        normalized = {key: _text(item[key], f"{field}.{key}") for key in keys}
        if field == "conditions" and normalized["operator"] not in _CONDITION_OPERATORS:
            raise ExpertRuleValidationError("Invalid conditions.operator.")
        result.append(normalized)
    return result


def _condition_value_is_valid(value_type: str, value: Any) -> bool:
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "null":
        return value is None
    return isinstance(value, list) and all(item is None or isinstance(item, (str, int, float, bool)) for item in value)


def _resolve_column(column_resolver: Callable[[Any], Any] | None, reference: Any, dataset_id: int) -> Any:
    if column_resolver is None:
        return None
    resolved = column_resolver(reference)
    candidates = resolved if isinstance(resolved, list) else [resolved]
    matches = [
        column for column in candidates if column is not None and getattr(column, "dataset_id", None) == dataset_id
    ]
    if len(matches) != 1:
        raise ExpertRuleValidationError("Invalid condition field reference.")
    return matches[0]


def _conditions(
    value: Any, schema_version: int, dataset_id: int, column_resolver: Callable[[Any], Any] | None
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ExpertRuleValidationError("Invalid conditions.")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ExpertRuleValidationError("Invalid conditions.")
        if schema_version == 1:
            if set(item) != {"field", "operator", "value"} or not isinstance(item["field"], str):
                raise ExpertRuleValidationError("Invalid legacy conditions.")
            column = _resolve_column(column_resolver, item["field"], dataset_id)
            if column is None:
                raise ExpertRuleValidationError("Column resolver is required.")
            value = item["value"]
            value_type = (
                "null"
                if value is None
                else "boolean"
                if isinstance(value, bool)
                else "number"
                if isinstance(value, (int, float))
                else "array"
                if isinstance(value, list)
                else "string"
                if isinstance(value, str)
                else "invalid"
            )
            item = {
                "field_ref": {"column_dictionary_id": column.id},
                "operator": item["operator"],
                "value_type": value_type,
                "value": value,
            }
        if (
            set(item) != {"field_ref", "operator", "value_type", "value"}
            or not isinstance(item["field_ref"], dict)
            or set(item["field_ref"]) != {"column_dictionary_id"}
        ):
            raise ExpertRuleValidationError("Invalid conditions.")
        column_id = item["field_ref"]["column_dictionary_id"]
        if (
            isinstance(column_id, bool)
            or not isinstance(column_id, int)
            or item["operator"] not in _CONDITION_OPERATORS
            or item["value_type"] not in _VALUE_TYPES
            or not _condition_value_is_valid(item["value_type"], item["value"])
        ):
            raise ExpertRuleValidationError("Invalid conditions.")
        if item["operator"] in {"is_null", "is_not_null"} and item["value"] is not None:
            raise ExpertRuleValidationError("Invalid conditions.")
        if column_resolver is not None:
            _resolve_column(column_resolver, column_id, dataset_id)
        result.append(
            {
                "field_ref": {"column_dictionary_id": column_id},
                "operator": item["operator"],
                "value_type": item["value_type"],
                "value": item["value"],
            }
        )
    return result


def normalize_rule_payload(payload: Any, column_resolver: Callable[[Any], Any] | None = None) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "name",
        "dataset_id",
        "conditions",
        "exceptions",
        "examples",
        "glossary_term_ids",
        "metric_ids",
    }
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ExpertRuleValidationError("Unsupported expert-rule fields.")
    dataset_id = payload.get("dataset_id")
    if isinstance(dataset_id, bool) or not isinstance(dataset_id, int):
        raise ExpertRuleValidationError("Invalid dataset_id.")
    schema_version = payload.get("schema_version", 1)
    if schema_version not in {1, 2}:
        raise ExpertRuleValidationError("Invalid schema_version.")
    return {
        "schema_version": 2,
        "name": _text(payload.get("name"), "name", MAX_NAME),
        "normalized_name": " ".join(payload["name"].split()).casefold(),
        "dataset_id": dataset_id,
        "conditions": _conditions(payload.get("conditions"), schema_version, dataset_id, column_resolver),
        # Many rules hold without exception; examples stay required because they show how the rule is asked about.
        "exceptions": _items(payload.get("exceptions"), "exceptions", {"when", "outcome"}, allow_empty=True),
        "examples": _items(payload.get("examples"), "examples", {"question", "intent"}),
        "glossary_term_ids": _id_list(payload.get("glossary_term_ids", []), "glossary_term_ids"),
        "metric_ids": _id_list(payload.get("metric_ids", []), "metric_ids"),
    }


def validate_semantic_links(
    payload: dict[str, Any],
    dataset_resolver: Callable[[int], Any],
    glossary_resolver: Callable[[int], Any],
    metric_resolver: Callable[[int], Any],
) -> None:
    if dataset_resolver(payload["dataset_id"]) is None:
        raise ExpertRuleValidationError("Unknown dataset.")
    if not payload["glossary_term_ids"]:
        raise ExpertRuleValidationError("An expert rule needs at least one approved glossary term.")
    for term_id in payload["glossary_term_ids"]:
        resolved = glossary_resolver(term_id)
        terms = resolved if isinstance(resolved, list) else [resolved]
        matching_term = next(
            (
                term
                for term in terms
                if term is not None
                and getattr(term, "status", None) == "approved"
                and getattr(term, "is_current", False)
                and getattr(term, "dataset_id", None) == payload["dataset_id"]
            ),
            None,
        )
        if matching_term is None:
            raise ExpertRuleValidationError("Invalid glossary link.")
    for metric_id in payload["metric_ids"]:
        metric = metric_resolver(metric_id)
        if (
            metric is None
            or getattr(metric, "status", None) != "approved"
            or not getattr(metric, "is_current", False)
            or getattr(metric, "dataset_id", None) != payload["dataset_id"]
        ):
            raise ExpertRuleValidationError("Invalid metric link.")


def rule_is_discoverable(revision: Any, links: list[Any], live_fingerprint: Callable[[Any], str | None]) -> bool:
    return bool(
        getattr(revision, "status", None) == "approved"
        and getattr(revision, "is_current", False)
        and links
        and all(live_fingerprint(link) == link.fingerprint for link in links)
    )


def _hash(values: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _lock(session: Any, revision: Any) -> Any:
    from ..repositories.expert_rule import ExpertRuleRepository
    from ..repositories.expert_rule_revision import ExpertRuleRevisionRepository

    rule = ExpertRuleRepository(session).lock(revision.rule_id)
    current = ExpertRuleRevisionRepository(session).lock_current(revision.rule_id)
    if rule is None or current is None or current.id != revision.id:
        raise ExpertRuleConflictError("The expert rule changed; refresh and retry.")
    return current


def _links(values: dict[str, Any], fingerprint: Callable[[str, int, int], str]) -> list[dict[str, Any]]:
    refs = [
        ("dataset", values["dataset_id"]),
        *(("glossary", item) for item in values["glossary_term_ids"]),
        *(("metric", item) for item in values["metric_ids"]),
    ]
    return [
        {
            "kind": kind,
            "target_id": target_id,
            "dataset_id": values["dataset_id"],
            "fingerprint": fingerprint(kind, target_id, values["dataset_id"]),
        }
        for kind, target_id in refs
    ]


def create_draft(
    session: Any,
    payload: Any,
    actor_id: int,
    dataset_resolver: Callable[[int], Any],
    glossary_resolver: Callable[[int], Any],
    metric_resolver: Callable[[int], Any],
    fingerprint: Callable[[str, int, int], str],
    column_resolver: Callable[[Any], Any] | None = None,
) -> Any:
    from ..models import ExpertRule, ExpertRuleAuditEvent, ExpertRuleLink, ExpertRuleRevision
    from ..repositories.expert_rule import ExpertRuleRepository
    from ..repositories.expert_rule_audit_event import ExpertRuleAuditEventRepository
    from ..repositories.expert_rule_link import ExpertRuleLinkRepository
    from ..repositories.expert_rule_revision import ExpertRuleRevisionRepository

    values = normalize_rule_payload(payload, column_resolver)
    validate_semantic_links(values, dataset_resolver, glossary_resolver, metric_resolver)
    rule_repository = ExpertRuleRepository(session)
    if rule_repository.by_normalized_name(values["normalized_name"]) is not None:
        raise ExpertRuleConflictError("An expert rule with this name already exists.")
    rule = ExpertRule(normalized_name=values["normalized_name"], dataset_id=values["dataset_id"])
    rule_repository.add(rule)
    revision = ExpertRuleRevision(
        rule_id=rule.id,
        revision_number=1,
        lifecycle_version=1,
        name=values["name"],
        conditions=values["conditions"],
        exceptions=values["exceptions"],
        examples=values["examples"],
        content_hash=_hash(values),
        status="draft",
        is_current=True,
    )
    ExpertRuleRevisionRepository(session).add(revision)
    link_repository = ExpertRuleLinkRepository(session)
    for link in _links(values, fingerprint):
        link_repository.add(ExpertRuleLink(revision_id=revision.id, **link), flush=False)
    ExpertRuleAuditEventRepository(session).add(
        ExpertRuleAuditEvent(
            rule_id=rule.id,
            revision_id=revision.id,
            event_type="created",
            actor_id=actor_id,
            revision_number=1,
            lifecycle_version=1,
            occurred_at=datetime.now(timezone.utc),
        ),
        flush=False,
    )
    return revision


def update_draft(
    session: Any,
    revision: Any,
    payload: Any,
    expected_revision: int,
    actor_id: int,
    dataset_resolver: Callable[[int], Any],
    glossary_resolver: Callable[[int], Any],
    metric_resolver: Callable[[int], Any],
    fingerprint: Callable[[str, int, int], str],
    column_resolver: Callable[[Any], Any] | None = None,
) -> Any:
    from ..models import ExpertRuleAuditEvent, ExpertRuleLink, ExpertRuleRevision
    from ..repositories.expert_rule_audit_event import ExpertRuleAuditEventRepository
    from ..repositories.expert_rule_link import ExpertRuleLinkRepository
    from ..repositories.expert_rule_revision import ExpertRuleRevisionRepository

    revision = _lock(session, revision)
    if revision.lifecycle_version != expected_revision:
        raise ExpertRuleConflictError("The expert rule changed; refresh and retry.")
    # A revoked rule stays current so its author can correct it and send it for review again.
    if revision.status not in {"draft", "approved", "revoked"}:
        raise ExpertRuleValidationError("Only a current expert rule can be updated.")
    values = normalize_rule_payload(payload, column_resolver)
    validate_semantic_links(values, dataset_resolver, glossary_resolver, metric_resolver)
    # Do not rely on an unloaded ORM relationship: ``_lock`` deliberately
    # resolved the authoritative rule under a row lock for this transaction.
    from ..repositories.expert_rule import ExpertRuleRepository

    rule = ExpertRuleRepository(session).find(revision.rule_id)
    if rule is None or values["dataset_id"] != rule.dataset_id:
        raise ExpertRuleValidationError("An expert rule cannot move datasets.")
    revision.is_current = False
    next_revision = ExpertRuleRevision(
        rule_id=revision.rule_id,
        revision_number=revision.revision_number + 1,
        lifecycle_version=revision.lifecycle_version + 1,
        name=values["name"],
        conditions=values["conditions"],
        exceptions=values["exceptions"],
        examples=values["examples"],
        content_hash=_hash(values),
        status="draft",
        is_current=True,
    )
    ExpertRuleRevisionRepository(session).add(next_revision)
    link_repository = ExpertRuleLinkRepository(session)
    for link in _links(values, fingerprint):
        link_repository.add(ExpertRuleLink(revision_id=next_revision.id, **link), flush=False)
    ExpertRuleAuditEventRepository(session).add(
        ExpertRuleAuditEvent(
            rule_id=revision.rule_id,
            revision_id=next_revision.id,
            event_type="updated",
            actor_id=actor_id,
            revision_number=next_revision.revision_number,
            lifecycle_version=next_revision.lifecycle_version,
            occurred_at=datetime.now(timezone.utc),
        ),
        flush=False,
    )
    return next_revision


def revision_author_id(session: Any, revision: Any) -> int | None:
    """The administrator who wrote this revision's content, from its created or updated audit event."""
    from ..repositories.expert_rule_audit_event import ExpertRuleAuditEventRepository

    event = ExpertRuleAuditEventRepository(session).latest_authoring(revision.id)
    return None if event is None else event.actor_id


def _transition(
    session: Any,
    revision: Any,
    expected_revision: int,
    actor_id: int,
    action: str,
    reason: str | None = None,
    require_second_reviewer: bool = False,
) -> Any:
    from ..models import ExpertRuleAuditEvent
    from ..repositories.expert_rule_audit_event import ExpertRuleAuditEventRepository

    revision = _lock(session, revision)
    if revision.lifecycle_version != expected_revision:
        raise ExpertRuleConflictError("The expert rule changed; refresh and retry.")
    clean_reason = _reason(reason)
    approving_draft = action == "approved" and revision.status == "draft"
    if approving_draft and require_second_reviewer and revision_author_id(session, revision) == actor_id:
        raise ExpertRuleSelfApprovalError()
    if action == "approved" and revision.status == "draft":
        revision.status, revision.approver_id, revision.approved_at = "approved", actor_id, datetime.now(timezone.utc)
    elif action == "revoked" and revision.status == "approved" and clean_reason:
        revision.status, revision.revoker_id, revision.revoked_at = "revoked", actor_id, datetime.now(timezone.utc)
    else:
        raise ExpertRuleValidationError(f"Cannot {action} this expert rule.")
    revision.lifecycle_version += 1
    ExpertRuleAuditEventRepository(session).add(
        ExpertRuleAuditEvent(
            rule_id=revision.rule_id,
            revision_id=revision.id,
            event_type=action,
            actor_id=actor_id,
            reason=clean_reason,
            revision_number=revision.revision_number,
            lifecycle_version=revision.lifecycle_version,
            occurred_at=datetime.now(timezone.utc),
        ),
        flush=False,
    )
    return revision


def approve_rule(
    session: Any,
    revision: Any,
    expected_revision: int,
    actor_id: int,
    reason: str | None = None,
    require_second_reviewer: bool = False,
) -> Any:
    return _transition(session, revision, expected_revision, actor_id, "approved", reason, require_second_reviewer)


def revoke_rule(session: Any, revision: Any, expected_revision: int, actor_id: int, reason: str | None = None) -> Any:
    return _transition(session, revision, expected_revision, actor_id, "revoked", reason)
