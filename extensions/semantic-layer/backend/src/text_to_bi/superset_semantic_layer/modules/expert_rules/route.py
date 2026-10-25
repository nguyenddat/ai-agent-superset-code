"""Admin lifecycle and permission-filtered discovery for expert rules."""

from __future__ import annotations

import hashlib
import json
from functools import wraps
from typing import Any

from flask import current_app, request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from flask_wtf.csrf import validate_csrf
from sqlalchemy.exc import IntegrityError
from superset import db, security_manager
from superset.connectors.sqla.models import SqlaTable
from superset.exceptions import SupersetSecurityException
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api
from wtforms import ValidationError

from ...models.column_dictionary import ColumnDictionary
from ...models.dataset_dictionary import DatasetDictionary
from ...models.expert_rule import ExpertRule, ExpertRuleAuditEvent, ExpertRuleLink, ExpertRuleRevision
from ...models.glossary_term import GlossaryTerm, GlossaryTermLink, GlossaryTermRevision
from ...models.metric_contract import MetricContract
from ..semantic_query.contracts import contract_is_approved_current, metric_contract_hash
from .service import (
    ExpertRuleConflictError,
    ExpertRuleSelfApprovalError,
    ExpertRuleValidationError,
    approve_rule,
    create_draft,
    revision_author_id,
    revoke_rule,
    rule_is_discoverable,
    update_draft,
)


def _csrf_protected(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return self.response(403, message="Invalid CSRF token.")
        return method(self, *args, **kwargs)
    return wrapped


def _rollback_on_error(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:  # noqa: BLE001 -- request-boundary rollback must contain unknown persistence errors.
            db.session.rollback()
            return self.response_500(message="Could not save the change.")
    return wrapped


@api(id="text_to_bi_expert_rule_api", name="Text to BI Expert Rules", resource_name="expert-rules")
class ExpertRuleAPI(RestApi):
    class_permission_name = "text_to_bi_expert_rule_api"

    @staticmethod
    def _is_admin() -> bool:
        return bool(getattr(current_user, "is_authenticated", False) and any(role.name == "Admin" for role in getattr(current_user, "roles", [])))

    @staticmethod
    def can_access_datasource(dataset: SqlaTable) -> bool:
        try:
            security_manager.raise_for_access(datasource=dataset)
        except SupersetSecurityException:
            return False
        return True

    @staticmethod
    def _dataset(dataset_id: int): return db.session.get(SqlaTable, dataset_id)

    @staticmethod
    def _column_resolver(dataset_id: int):
        """Resolve only stable dictionary IDs/names within the rule's dataset."""
        if db.session.get(DatasetDictionary, dataset_id) is None:
            return lambda _: None

        def resolve(reference: Any):
            query = db.session.query(ColumnDictionary).filter_by(dataset_id=dataset_id)
            if isinstance(reference, int) and not isinstance(reference, bool):
                return query.filter_by(id=reference).one_or_none()
            if isinstance(reference, str):
                return query.filter_by(column_name=reference).all()
            return None

        return resolve

    @staticmethod
    def _glossary(term_id: int):
        revision = db.session.query(GlossaryTermRevision).filter_by(term_id=term_id, status="approved", is_current=True).one_or_none()
        if revision is None: return None
        # A term may describe multiple datasets. Resolve deterministically and
        # leave same-dataset enforcement to the service using this link's ID.
        links = db.session.query(GlossaryTermLink).filter_by(revision_id=revision.id).order_by(GlossaryTermLink.id).all()
        return [
            type("GlossaryLink", (), {"status": revision.status, "is_current": revision.is_current, "dataset_id": link.dataset_id,
                                       "content_hash": revision.content_hash, "fingerprint": link.fingerprint})()
            for link in links
        ]

    @staticmethod
    def _metric(metric_id: int):
        contracts = db.session.query(MetricContract).filter_by(metric_id=metric_id).all()
        for contract in contracts:
            dataset = db.session.get(SqlaTable, contract.dataset_id)
            metric = next((item for item in getattr(dataset, "metrics", []) if item.id == metric_id), None) if dataset else None
            if dataset and metric and contract_is_approved_current(contract, dataset, metric):
                return type("MetricLink", (), {"status": contract.status, "is_current": True, "dataset_id": dataset.id,
                                                  "expression_hash": metric_contract_hash(dataset, metric)})()
        return None

    def _fingerprint(self, kind: str, target_id: int, dataset_id: int) -> str:
        # Only stable metadata identifiers/statuses are fingerprinted; no connection or SQL text is exposed.
        source: Any = self._dataset(dataset_id) if kind == "dataset" else self._glossary(target_id) if kind == "glossary" else self._metric(target_id)
        if kind == "glossary":
            source = next((link for link in source or [] if link.dataset_id == dataset_id), None)
        if source is None:
            return None
        identity = [kind, target_id, dataset_id, getattr(source, "status", None), getattr(source, "is_current", None)]
        if kind == "metric": identity.append(getattr(source, "expression_hash", None))
        if kind == "glossary": identity.extend([getattr(source, "content_hash", None), getattr(source, "fingerprint", None)])
        return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _revision(rule_id: int): return db.session.query(ExpertRuleRevision).filter_by(rule_id=rule_id, is_current=True).one_or_none()

    @staticmethod
    def _expected(payload: Any) -> int:
        value = payload.get("expected_revision") if isinstance(payload, dict) else None
        if isinstance(value, bool) or not isinstance(value, int): raise ExpertRuleValidationError("expected_revision is required.")
        return value

    @staticmethod
    def _serialize(revision: ExpertRuleRevision, redact: bool = False) -> dict[str, Any]:
        value = {"id": revision.rule_id, "revision": revision.revision_number, "lifecycle_version": revision.lifecycle_version, "schema_version": 2, "status": revision.status, "name": revision.name}
        if not redact: value.update({"conditions": revision.conditions, "exceptions": revision.exceptions, "examples": revision.examples})
        return value

    def _mutate(self, operation, rule_id: int | None = None):
        if not self._is_admin(): return self.response(403, message="Admin access required.")
        # Tables are provisioned only by the separately approved bootstrap/
        # migration gate. Request paths must never issue metadata DDL.
        payload = request.get_json(silent=True)
        try:
            if not isinstance(payload, dict):
                raise ExpertRuleValidationError("Request body must be an object.")
            if rule_id is None: revision = operation(payload)
            else:
                revision = self._revision(rule_id)
                if revision is None: return self.response(404, message="Expert rule not found.")
                result = operation(revision, payload)
                revision = revision if result is None else result
            db.session.commit()
            return self.response(201 if rule_id is None else 200, rule=self._serialize(revision))
        except ExpertRuleConflictError as ex:
            db.session.rollback(); return self.response(409, message=str(ex))
        except ExpertRuleSelfApprovalError as ex:
            db.session.rollback(); return self.response(403, message=str(ex))
        except ExpertRuleValidationError as ex:
            db.session.rollback(); return self.response_400(message=str(ex))
        except IntegrityError:
            db.session.rollback(); return self.response_400(message="Could not save the expert rule.")

    @expose("/expert-rules", methods=["POST"])
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def create_rule(self):
        if not self._is_admin(): return self.response(403, message="Admin access required.")
        return self._mutate(lambda payload: create_draft(db.session, payload, current_user.id, self._dataset, self._glossary, self._metric, self._fingerprint, self._column_resolver(payload.get("dataset_id"))))

    @expose("/expert-rules/<int:rule_id>/draft", methods=["PUT"])
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def update_rule(self, rule_id: int):
        if not self._is_admin(): return self.response(403, message="Admin access required.")
        return self._mutate(lambda revision, payload: update_draft(db.session, revision, {k: v for k, v in payload.items() if k != "expected_revision"}, self._expected(payload), current_user.id, self._dataset, self._glossary, self._metric, self._fingerprint, self._column_resolver(payload.get("dataset_id"))), rule_id)

    @expose("/expert-rules/<int:rule_id>/approve", methods=["POST"])
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def approve(self, rule_id: int):
        if not self._is_admin(): return self.response(403, message="Admin access required.")
        return self._mutate(
            lambda revision, payload: approve_rule(
                db.session, revision, self._expected(payload), current_user.id, payload.get("reason"),
                require_second_reviewer=self._second_reviewer_required(),
            ),
            rule_id,
        )

    @staticmethod
    def _second_reviewer_required() -> bool:
        """Whether a proposal's author must leave its approval to another administrator.

        Off by default so a single administrator can approve their own work; a deployment with several reviewers
        sets TEXT_TO_BI_REQUIRE_SECOND_REVIEWER = True in superset_config.
        """
        return bool(current_app.config.get("TEXT_TO_BI_REQUIRE_SECOND_REVIEWER", False))

    @expose("/expert-rules/<int:rule_id>/revoke", methods=["POST"])
    @protect()
    @safe
    @permission_name("write")
    @_csrf_protected
    @_rollback_on_error
    def revoke(self, rule_id: int):
        if not self._is_admin(): return self.response(403, message="Admin access required.")
        return self._mutate(lambda revision, payload: revoke_rule(db.session, revision, self._expected(payload), current_user.id, payload.get("reason")), rule_id)

    @expose("/expert-rules/<int:rule_id>/audit", methods=["GET"])
    @protect()
    @safe
    @permission_name("read")
    def audit(self, rule_id: int):
        if not self._is_admin(): return self.response(403, message="Admin access required.")
        events = db.session.query(ExpertRuleAuditEvent).filter_by(rule_id=rule_id).order_by(ExpertRuleAuditEvent.id).all()
        user_name = self._user_names()
        audit = [
            {
                "action": event.event_type,
                "revision": event.revision_number,
                "lifecycle_version": event.lifecycle_version,
                "actor_id": event.actor_id,
                "actor_name": user_name(event.actor_id),
                "reason": event.reason,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in events
        ]
        return self.response(200, audit=audit)

    @staticmethod
    def _user_names() -> Any:
        """A per-request lookup from user ID to display name: full name, else username."""
        names: dict[int, str | None] = {}

        def user_name(user_id: int | None) -> str | None:
            if user_id is None:
                return None
            if user_id not in names:
                user = security_manager.get_user_by_id(user_id)
                names[user_id] = (user.get_full_name().strip() or user.username) if user else None
            return names[user_id]

        return user_name

    @staticmethod
    def _review_revisions() -> list[ExpertRuleRevision]:
        """Each rule's current revision; a rule revoked while revocation still retired it falls back to its latest."""
        latest: dict[int, ExpertRuleRevision] = {}
        for revision in db.session.query(ExpertRuleRevision).order_by(ExpertRuleRevision.revision_number).all():
            kept = latest.get(revision.rule_id)
            if kept is None or revision.is_current or not kept.is_current:
                latest[revision.rule_id] = revision
        return list(latest.values())

    def _review_state(self, revision: ExpertRuleRevision, links: list[ExpertRuleLink]) -> str:
        if revision.status != "approved":
            return revision.status
        live = rule_is_discoverable(revision, links, self._live_fingerprint)
        # An approved rule whose linked metric or term changed since approval is hidden from discovery.
        return "approved" if live else "outdated"

    def _live_fingerprint(self, link: ExpertRuleLink) -> str | None:
        return self._fingerprint(link.kind, link.target_id, link.dataset_id)

    @staticmethod
    def _glossary_term_name(term_id: int) -> str:
        term = db.session.get(GlossaryTerm, term_id)
        return term.canonical_name if term else f"#{term_id}"

    @staticmethod
    def _column_name(column_id: int) -> str:
        column = db.session.get(ColumnDictionary, column_id)
        return (column.display_name or column.column_name) if column else f"#{column_id}"

    @expose("/expert-rules", methods=["GET"])
    @protect()
    @safe
    @permission_name("read")
    def list_rules(self):
        """Every rule with its current revision and review state, for the administrator review page."""
        if not self._is_admin(): return self.response(403, message="Admin access required.")
        user_name = self._user_names()
        rules = []
        for revision in self._review_revisions():
            rule = db.session.get(ExpertRule, revision.rule_id)
            dataset = self._dataset(rule.dataset_id) if rule else None
            links = db.session.query(ExpertRuleLink).filter_by(revision_id=revision.id).all()
            metrics = getattr(dataset, "metrics", [])
            metric_names = {metric.id: metric.verbose_name or metric.metric_name for metric in metrics}
            column_ids = {condition["field_ref"]["column_dictionary_id"] for condition in revision.conditions}
            author_id = revision_author_id(db.session, revision)
            rules.append({
                **self._serialize(revision),
                "dataset_id": rule.dataset_id if rule else None,
                "dataset_name": getattr(dataset, "table_name", None),
                "state": self._review_state(revision, links),
                "column_names": {str(column_id): self._column_name(column_id) for column_id in column_ids},
                "glossary_terms": [
                    {"id": link.target_id, "name": self._glossary_term_name(link.target_id)}
                    for link in links if link.kind == "glossary"
                ],
                "metrics": [
                    {"id": link.target_id, "name": metric_names.get(link.target_id, f"#{link.target_id}")}
                    for link in links if link.kind == "metric"
                ],
                "author_id": author_id,
                "author_name": user_name(author_id),
                "approver_name": user_name(revision.approver_id),
                "approved_at": revision.approved_at.isoformat() if revision.approved_at else None,
                "revoker_name": user_name(revision.revoker_id),
                "revoked_at": revision.revoked_at.isoformat() if revision.revoked_at else None,
            })
        rules.sort(key=lambda item: item["name"].casefold())
        return self.response(
            200, rules=rules, current_user_id=current_user.id, require_second_reviewer=self._second_reviewer_required()
        )

    @expose("/expert-rules/options", methods=["GET"])
    @protect()
    @safe
    @permission_name("read")
    def rule_options(self):
        """What a rule editor may reference per dataset: dictionary columns, approved glossary terms and metrics."""
        if not self._is_admin(): return self.response(403, message="Admin access required.")
        terms_by_dataset: dict[int, list[dict[str, Any]]] = {}
        for revision in db.session.query(GlossaryTermRevision).filter_by(status="approved", is_current=True).all():
            term = {"id": revision.term_id, "name": self._glossary_term_name(revision.term_id)}
            links = db.session.query(GlossaryTermLink).filter_by(revision_id=revision.id).all()
            for dataset_id in {link.dataset_id for link in links}:
                terms_by_dataset.setdefault(dataset_id, []).append(term)
        datasets = []
        for dictionary in db.session.query(DatasetDictionary).all():
            dataset = self._dataset(dictionary.id)
            if dataset is None or not self.can_access_datasource(dataset):
                continue
            columns = (
                db.session.query(ColumnDictionary).filter_by(dataset_id=dataset.id).order_by(ColumnDictionary.id).all()
            )
            datasets.append({
                "id": dataset.id,
                "name": dataset.table_name,
                "columns": [
                    {"id": column.id, "column_name": column.column_name, "display_name": column.display_name,
                     "data_type": column.data_type}
                    for column in columns
                ],
                "glossary_terms": sorted(
                    terms_by_dataset.get(dataset.id, []), key=lambda term: term["name"].casefold()
                ),
                "metrics": [
                    {"id": metric.id, "name": metric.verbose_name or metric.metric_name}
                    for metric in getattr(dataset, "metrics", []) if self._metric(metric.id) is not None
                ],
            })
        datasets.sort(key=lambda item: item["name"].casefold())
        return self.response(200, datasets=datasets)

    @expose("/expert-rules/discover", methods=["GET"])
    @protect()
    @safe
    @permission_name("read")
    def discover(self):
        rules = []
        for revision in db.session.query(ExpertRuleRevision).filter_by(status="approved", is_current=True).all():
            rule = db.session.get(ExpertRule, revision.rule_id); dataset = self._dataset(rule.dataset_id)
            if dataset is None or not self.can_access_datasource(dataset): continue
            links = db.session.query(ExpertRuleLink).filter_by(revision_id=revision.id).all()
            if not all(self._linked_target_authorized(link) for link in links):
                continue
            if rule_is_discoverable(revision, links, lambda link: self._fingerprint(link.kind, link.target_id, link.dataset_id)):
                rules.append(self._serialize(revision, redact=False))
        return self.response(200, rules=rules)

    def _linked_target_authorized(self, link: ExpertRuleLink) -> bool:
        """Fail closed: any inaccessible or stale semantic target hides its rule."""
        dataset = self._dataset(link.dataset_id)
        if dataset is None or not self.can_access_datasource(dataset):
            return False
        if link.kind == "dataset":
            return True
        if link.kind == "metric":
            return self._metric(link.target_id) is not None
        glossary_links = self._glossary(link.target_id)
        # A glossary term can have bindings for several datasets. This rule is
        # governed by its own dataset binding, so an inaccessible unrelated
        # binding must not hide otherwise authorized metadata.
        glossary_link = next((item for item in glossary_links or [] if item.dataset_id == link.dataset_id), None)
        dataset = self._dataset(glossary_link.dataset_id) if glossary_link is not None else None
        return bool(dataset is not None and self.can_access_datasource(dataset))
