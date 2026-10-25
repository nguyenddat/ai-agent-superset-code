"""Validation, lifecycle, and safe serialization for governed glossary terms."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError

from ..semantic_query.contracts import safe_connection_identity

MAX_NAME_LENGTH = 255
MAX_DEFINITION_LENGTH = 10_000
MAX_SYNONYMS = 50
MAX_REASON_LENGTH = 512
PROVENANCE = {"manual", "import", "ai_suggestion"}
LINK_KINDS = {"dataset", "column", "metric"}
SOURCE_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")


class GlossaryValidationError(ValueError):
    """A client-visible validation error that contains no protected metadata."""


class GlossaryConflictError(ValueError):
    """An optimistic concurrency conflict."""


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _required_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not (result := " ".join(value.split())):
        raise GlossaryValidationError(f"{field} must be a non-empty string.")
    if len(result) > limit:
        raise GlossaryValidationError(f"{field} is too long.")
    return result


def extract_glossary_update_payload(payload: Any) -> tuple[dict[str, Any], int]:
    """Separate the transport-only optimistic lock token from glossary content."""
    if not isinstance(payload, dict):
        raise GlossaryValidationError("Unsupported glossary fields.")
    expected_revision = payload.get("expected_revision")
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise GlossaryValidationError("expected_revision is required.")
    return {key: value for key, value in payload.items() if key != "expected_revision"}, expected_revision


def normalize_glossary_payload(payload: Any) -> dict[str, Any]:
    """Reject unknown fields and canonicalize text before persistence."""
    allowed = {"canonical_name", "definition", "synonyms", "provenance", "source_hash", "owner_id", "steward_id", "links"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise GlossaryValidationError("Unsupported glossary fields.")
    name = _required_text(payload.get("canonical_name"), "canonical_name", MAX_NAME_LENGTH)
    definition = _required_text(payload.get("definition"), "definition", MAX_DEFINITION_LENGTH)
    provenance = payload.get("provenance")
    if provenance not in PROVENANCE:
        raise GlossaryValidationError("Unsupported provenance.")
    synonyms = payload.get("synonyms", [])
    if not isinstance(synonyms, list) or len(synonyms) > MAX_SYNONYMS:
        raise GlossaryValidationError("synonyms must be a bounded array.")
    normalized_name = _normalized(name)
    clean_synonyms: list[str] = []
    seen = {normalized_name}
    for synonym in synonyms:
        clean = _required_text(synonym, "synonym", MAX_NAME_LENGTH)
        normalized = _normalized(clean)
        if normalized in seen:
            if normalized == normalized_name:
                raise GlossaryValidationError("A synonym cannot duplicate the canonical name.")
            continue
        seen.add(normalized)
        clean_synonyms.append(clean)
    links = payload.get("links")
    if not isinstance(links, list) or not links:
        raise GlossaryValidationError("At least one glossary link is required.")
    for link in links:
        if not isinstance(link, dict) or set(link) - {"kind", "dataset_id", "column_name", "metric_id"}:
            raise GlossaryValidationError("Invalid glossary link.")
        if link.get("kind") not in LINK_KINDS or isinstance(link.get("dataset_id"), bool) or not isinstance(link.get("dataset_id"), int):
            raise GlossaryValidationError("Invalid glossary link.")
    for field in ("owner_id", "steward_id"):
        if field in payload and payload[field] is not None and (isinstance(payload[field], bool) or not isinstance(payload[field], int)):
            raise GlossaryValidationError(f"{field} must be a user id.")
    source_hash = payload.get("source_hash")
    if source_hash is not None and (not isinstance(source_hash, str) or not SOURCE_HASH.fullmatch(source_hash)):
        raise GlossaryValidationError("Invalid source hash.")
    return {**payload, "canonical_name": name, "normalized_name": normalized_name, "definition": definition, "synonyms": clean_synonyms}


def glossary_link_fingerprint(dataset: Any, kind: str, target: Any | None = None) -> str:
    """Bind a link to live safe metadata, excluding connection credentials."""
    if kind not in LINK_KINDS:
        raise GlossaryValidationError("Unsupported glossary link kind.")
    payload = {
        "kind": kind, "dataset_id": getattr(dataset, "id", None), "catalog": getattr(dataset, "catalog", None),
        "schema": getattr(dataset, "schema", None), "table": getattr(dataset, "table_name", None),
        "sql": getattr(dataset, "sql", None), "database": safe_connection_identity(getattr(dataset, "database", None)),
    }
    if kind == "column":
        payload["column"] = getattr(target, "column_name", None)
        payload["active"] = getattr(target, "is_active", None)
        payload["expression"] = getattr(target, "expression", None)
    elif kind == "metric":
        payload["metric_id"] = getattr(target, "id", None)
        payload["metric_name"] = getattr(target, "metric_name", None)
        payload["expression"] = getattr(target, "expression", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def revision_is_discoverable(revision: Any, links: list[Any], expected_fingerprint: Callable[[Any], str | None]) -> bool:
    return bool(getattr(revision, "status", None) == "approved" and getattr(revision, "is_current", False) and links and all(
        expected_fingerprint(link) is not None and expected_fingerprint(link) == getattr(link, "fingerprint", None) for link in links
    ))


def _content_hash(payload: dict[str, Any]) -> str:
    values = {key: payload.get(key) for key in ("canonical_name", "definition", "synonyms", "provenance", "source_hash", "links")}
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _validated_links(session: Any, links: list[dict[str, Any]], dataset_resolver: Callable[[int], Any]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for raw in links:
        dataset = dataset_resolver(raw["dataset_id"])
        if dataset is None:
            raise GlossaryValidationError("Invalid glossary link.")
        kind = raw["kind"]
        target = None
        if kind == "column":
            name = raw.get("column_name")
            target = next((column for column in dataset.columns if getattr(column, "column_name", None) == name), None)
            if target is None or getattr(target, "is_active", None) is not True or getattr(target, "expression", None):
                raise GlossaryValidationError("Invalid glossary link.")
        elif kind == "metric":
            metric_id = raw.get("metric_id")
            target = next((metric for metric in dataset.metrics if getattr(metric, "id", None) == metric_id), None)
            if target is None:
                raise GlossaryValidationError("Invalid glossary link.")
        elif raw.get("column_name") is not None or raw.get("metric_id") is not None:
            raise GlossaryValidationError("Invalid glossary link.")
        values = {
            "kind": kind,
            "dataset_id": dataset.id,
            "column_name": getattr(target, "column_name", None),
            "metric_id": getattr(target, "id", None) if kind == "metric" else None,
            "link_key": f"{kind}:{dataset.id}:{getattr(target, 'column_name', '')}:{getattr(target, 'id', '')}",
            "fingerprint": glossary_link_fingerprint(dataset, kind, target),
        }
        key = (values["kind"], values["dataset_id"], values["column_name"], values["metric_id"])
        if key in seen:
            raise GlossaryValidationError("Duplicate glossary link.")
        seen.add(key)
        result.append(values)
    return result


def _lock_current_revision(session: Any, current: Any) -> Any:
    """Lock a term and re-read its current revision before a lifecycle mutation."""
    from ...models.glossary_term import GlossaryTerm, GlossaryTermRevision

    term = (
        session.query(GlossaryTerm)
        .filter(GlossaryTerm.id == current.term_id)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if term is None:
        raise GlossaryConflictError("The glossary term changed; refresh and retry.")
    locked = (
        session.query(GlossaryTermRevision)
        .filter_by(term_id=current.term_id, is_current=True)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if locked is None or locked.id != current.id:
        raise GlossaryConflictError("The glossary term changed; refresh and retry.")
    return locked


def create_draft(session: Any, payload: Any, actor_id: int, dataset_resolver: Callable[[int], Any], user_exists: Callable[[int], bool]) -> Any:
    from ...models.glossary_term import GlossaryTerm, GlossaryTermAuditEvent, GlossaryTermLink, GlossaryTermRevision

    values = normalize_glossary_payload(payload)
    for field in ("owner_id", "steward_id"):
        if values.get(field) is not None and not user_exists(values[field]):
            raise GlossaryValidationError(f"Unknown {field}.")
    if session.query(GlossaryTerm).filter_by(normalized_name=values["normalized_name"]).one_or_none() is not None:
        raise GlossaryConflictError("A glossary term with this canonical name already exists.")
    term = GlossaryTerm(canonical_name=values["canonical_name"], normalized_name=values["normalized_name"], owner_id=values.get("owner_id"), steward_id=values.get("steward_id"))
    session.add(term)
    try:
        session.flush()
    except IntegrityError as ex:
        session.rollback()
        raise GlossaryConflictError("A glossary term with this canonical name already exists.") from ex
    revision = GlossaryTermRevision(term_id=term.id, revision_number=1, definition=values["definition"], synonyms=values["synonyms"], provenance=values["provenance"], source_reference=None, source_hash=values.get("source_hash"), content_hash=_content_hash(values), status="draft", is_current=True)
    session.add(revision)
    session.flush()
    for link in _validated_links(session, values["links"], dataset_resolver):
        session.add(GlossaryTermLink(revision_id=revision.id, **link))
    session.add(GlossaryTermAuditEvent(term_id=term.id, revision_id=revision.id, event_type="created", actor_id=actor_id, revision_number=1, occurred_at=datetime.now(timezone.utc)))
    return revision


def update_draft(
    session: Any,
    current: Any,
    payload: Any,
    expected_revision: int,
    actor_id: int,
    dataset_resolver: Callable[[int], Any],
    user_exists: Callable[[int], bool],
) -> Any:
    """Replace the current draft with an immutable next revision."""
    from ...models.glossary_term import GlossaryTermAuditEvent, GlossaryTermLink, GlossaryTermRevision

    current = _lock_current_revision(session, current)
    if current.revision_number != expected_revision:
        raise GlossaryConflictError("The glossary term changed; refresh and retry.")
    if current.status not in {"draft", "approved"} or not current.is_current:
        raise GlossaryValidationError("Only a current draft or approved revision can be updated.")
    values = normalize_glossary_payload(payload)
    for field in ("owner_id", "steward_id"):
        if values.get(field) is not None and not user_exists(values[field]):
            raise GlossaryValidationError(f"Unknown {field}.")
    if values["normalized_name"] != current.term.normalized_name:
        raise GlossaryValidationError("The canonical name cannot be changed after creation.")
    current.term.owner_id = values.get("owner_id")
    current.term.steward_id = values.get("steward_id")
    current.is_current = False
    revision = GlossaryTermRevision(
        term_id=current.term_id, revision_number=current.revision_number + 1, definition=values["definition"],
        synonyms=values["synonyms"], provenance=values["provenance"], source_reference=None,
        source_hash=values.get("source_hash"), content_hash=_content_hash(values), status="draft", is_current=True,
    )
    session.add(revision)
    try:
        session.flush()
    except IntegrityError as ex:
        session.rollback()
        raise GlossaryConflictError("The glossary term changed; refresh and retry.") from ex
    for link in _validated_links(session, values["links"], dataset_resolver):
        session.add(GlossaryTermLink(revision_id=revision.id, **link))
    session.add(GlossaryTermAuditEvent(term_id=current.term_id, revision_id=revision.id, event_type="updated", actor_id=actor_id, revision_number=revision.revision_number, occurred_at=datetime.now(timezone.utc)))
    return revision


def approve_revision(session: Any, revision: Any, expected_revision: int, actor_id: int, reason: str | None = None) -> None:
    from ...models.glossary_term import GlossaryTermAuditEvent

    revision = _lock_current_revision(session, revision)
    if revision.revision_number != expected_revision:
        raise GlossaryConflictError("The glossary term changed; refresh and retry.")
    if revision.status != "draft" or not revision.is_current:
        raise GlossaryValidationError("Only the current draft can be approved.")
    if reason is not None and (not isinstance(reason, str) or len(reason) > MAX_REASON_LENGTH):
        raise GlossaryValidationError("Invalid approval reason.")
    revision.status, revision.approver_id, revision.approved_at = "approved", actor_id, datetime.now(timezone.utc)
    session.add(GlossaryTermAuditEvent(term_id=revision.term_id, revision_id=revision.id, event_type="approved", actor_id=actor_id, reason=reason, revision_number=revision.revision_number, occurred_at=revision.approved_at))


def revoke_revision(session: Any, revision: Any, expected_revision: int, actor_id: int, reason: str | None = None) -> None:
    from ...models.glossary_term import GlossaryTermAuditEvent

    revision = _lock_current_revision(session, revision)
    if revision.revision_number != expected_revision:
        raise GlossaryConflictError("The glossary term changed; refresh and retry.")
    if revision.status != "approved" or not revision.is_current:
        raise GlossaryValidationError("Only the current approved revision can be revoked.")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
        raise GlossaryValidationError("A bounded revocation reason is required.")
    revision.status, revision.is_current, revision.revoker_id, revision.revoked_at = "revoked", False, actor_id, datetime.now(timezone.utc)
    session.add(GlossaryTermAuditEvent(term_id=revision.term_id, revision_id=revision.id, event_type="revoked", actor_id=actor_id, reason=reason.strip(), revision_number=revision.revision_number, occurred_at=revision.revoked_at))
