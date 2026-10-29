from __future__ import annotations

import hashlib
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from superset import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ....common.utils.type_formatter import compact_json, iso_datetime
from ....core.database import handle_errors, rollback_on_error
from ....core.security import can_access_dataset, csrf_protected, require_admin, second_reviewer_required
from ...data_dictionary.dependencies import column_dictionary_repository, dataset_dictionary_repository
from ...glossary.dependencies import (
    glossary_term_link_repository,
    glossary_term_repository,
    glossary_term_revision_repository,
)
from ...glossary.models import GlossaryTermLink
from ...semantic_query.dependencies import metric_contract_repository
from ...semantic_query.services.contracts import contract_is_approved_current, metric_contract_hash
from ...superset.services.datasets import get_dataset
from ...superset.services.users import user_names
from ..dependencies import (
    expert_rule_audit_event_repository,
    expert_rule_link_repository,
    expert_rule_repository,
    expert_rule_revision_repository,
)
from ..exceptions import ExpertRuleNotFoundError, ExpertRuleValidationError
from ..models import ExpertRuleLink, ExpertRuleRevision
from ..services.expert_rule import (
    approve_rule,
    create_draft,
    revision_author_id,
    revoke_rule,
    rule_is_discoverable,
    update_draft,
)


@api(id="text_to_bi_expert_rule_api", name="Text to BI Expert Rules", resource_name="expert-rules")
class ExpertRuleAPI(RestApi):
    class_permission_name = "text_to_bi_expert_rule_api"

    @staticmethod
    def _dataset(dataset_id: int):
        return get_dataset(dataset_id)

    @staticmethod
    def _column_resolver(dataset_id: int):
        """Resolve only stable dictionary IDs/names within the rule's dataset."""
        if dataset_dictionary_repository().get(dataset_id) is None:
            return lambda _: None

        def resolve(reference: Any):
            query = column_dictionary_repository().in_dataset(dataset_id)
            if isinstance(reference, int) and not isinstance(reference, bool):
                return query.filter_by(id=reference).one_or_none()
            if isinstance(reference, str):
                return query.filter_by(column_name=reference).all()
            return None

        return resolve

    @staticmethod
    def _glossary(term_id: int):
        revision = glossary_term_revision_repository().approved_current_for(term_id)
        if revision is None:
            return None
        # A term may describe multiple datasets. Resolve deterministically and
        # leave same-dataset enforcement to the service using this link's ID.
        links = glossary_term_link_repository().for_revision_in_order(revision.id)
        return [
            type(
                "GlossaryLink",
                (),
                {
                    "status": revision.status,
                    "is_current": revision.is_current,
                    "dataset_id": link.dataset_id,
                    "content_hash": revision.content_hash,
                    "fingerprint": link.fingerprint,
                },
            )()
            for link in links
        ]

    @staticmethod
    def _metric(metric_id: int):
        contracts = metric_contract_repository().for_metric(metric_id)
        for contract in contracts:
            dataset = get_dataset(contract.dataset_id)
            metric = (
                next((item for item in getattr(dataset, "metrics", []) if item.id == metric_id), None)
                if dataset
                else None
            )
            if dataset and metric and contract_is_approved_current(contract, dataset, metric):
                return type(
                    "MetricLink",
                    (),
                    {
                        "status": contract.status,
                        "is_current": True,
                        "dataset_id": dataset.id,
                        "expression_hash": metric_contract_hash(dataset, metric),
                    },
                )()
        return None

    def _fingerprint(self, kind: str, target_id: int, dataset_id: int) -> str:
        # Only stable metadata identifiers/statuses are fingerprinted; no connection or SQL text is exposed.
        source: Any = (
            self._dataset(dataset_id)
            if kind == "dataset"
            else self._glossary(target_id)
            if kind == "glossary"
            else self._metric(target_id)
        )
        if kind == "glossary":
            source = next((link for link in source or [] if link.dataset_id == dataset_id), None)
        if source is None:
            return None
        identity = [kind, target_id, dataset_id, getattr(source, "status", None), getattr(source, "is_current", None)]
        if kind == "metric":
            identity.append(getattr(source, "expression_hash", None))
        if kind == "glossary":
            identity.extend([getattr(source, "content_hash", None), getattr(source, "fingerprint", None)])
        return hashlib.sha256(compact_json(identity).encode()).hexdigest()

    @staticmethod
    def _revision(rule_id: int):
        return expert_rule_revision_repository().current_for(rule_id)

    @staticmethod
    def _expected(payload: Any) -> int:
        value = payload.get("expected_revision") if isinstance(payload, dict) else None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ExpertRuleValidationError("expected_revision is required.")
        return value

    @staticmethod
    def _serialize(revision: ExpertRuleRevision, redact: bool = False) -> dict[str, Any]:
        value = {
            "id": revision.rule_id,
            "revision": revision.revision_number,
            "lifecycle_version": revision.lifecycle_version,
            "schema_version": 2,
            "status": revision.status,
            "name": revision.name,
        }
        if not redact:
            value.update(
                {"conditions": revision.conditions, "exceptions": revision.exceptions, "examples": revision.examples}
            )
        return value

    def _mutate(self, operation, rule_id: int | None = None):
        require_admin()
        # Tables are provisioned only by the separately approved bootstrap/
        # migration gate. Request paths must never issue metadata DDL.
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ExpertRuleValidationError("Request body must be an object.")
        if rule_id is not None:
            revision = self._revision(rule_id)
            if revision is None:
                raise ExpertRuleNotFoundError()
        # Repositories flush as they add rows, so a unique-name collision can surface inside the operation too.
        try:
            if rule_id is None:
                revision = operation(payload)
            else:
                result = operation(revision, payload)
                revision = revision if result is None else result
            db.session.commit()
        except IntegrityError as ex:
            raise ExpertRuleValidationError("Could not save the expert rule.") from ex
        return self.response(201 if rule_id is None else 200, rule=self._serialize(revision))

    @expose("/expert-rules", methods=["POST"])
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_rule(self):
        require_admin()
        return self._mutate(
            lambda payload: create_draft(
                db.session,
                self._with_term_metrics(payload),
                current_user.id,
                self._dataset,
                self._glossary,
                self._metric,
                self._fingerprint,
                self._column_resolver(payload.get("dataset_id")),
            )
        )

    @expose("/expert-rules/<int:rule_id>/draft", methods=["PUT"])
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_rule(self, rule_id: int):
        require_admin()

        def save(revision, payload):
            content = self._with_term_metrics(
                {key: value for key, value in payload.items() if key != "expected_revision"}
            )
            return update_draft(
                db.session,
                revision,
                content,
                self._expected(payload),
                current_user.id,
                self._dataset,
                self._glossary,
                self._metric,
                self._fingerprint,
                self._column_resolver(payload.get("dataset_id")),
            )

        return self._mutate(save, rule_id)

    @expose("/expert-rules/<int:rule_id>/approve", methods=["POST"])
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve(self, rule_id: int):
        require_admin()
        return self._mutate(
            lambda revision, payload: approve_rule(
                db.session,
                revision,
                self._expected(payload),
                current_user.id,
                payload.get("reason"),
                require_second_reviewer=second_reviewer_required(),
            ),
            rule_id,
        )

    @expose("/expert-rules/<int:rule_id>/revoke", methods=["POST"])
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke(self, rule_id: int):
        require_admin()
        return self._mutate(
            lambda revision, payload: revoke_rule(
                db.session, revision, self._expected(payload), current_user.id, payload.get("reason")
            ),
            rule_id,
        )

    @expose("/expert-rules/<int:rule_id>/audit", methods=["GET"])
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def audit(self, rule_id: int):
        require_admin()
        events = expert_rule_audit_event_repository().for_rule(rule_id)
        user_name = user_names()
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
    def _review_revisions() -> list[ExpertRuleRevision]:
        """Each rule's current revision; a rule revoked while revocation still retired it falls back to its latest."""
        latest: dict[int, ExpertRuleRevision] = {}
        for revision in expert_rule_revision_repository().by_revision_number():
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

    def _term_links(self, term_id: int, dataset_id: int) -> list[GlossaryTermLink]:
        """The approved current revision's links of a term into one dataset."""
        revision = glossary_term_revision_repository().approved_current_for(term_id)
        if revision is None:
            return []
        return glossary_term_link_repository().for_revision_dataset(revision.id, dataset_id)

    def _with_term_metrics(self, payload: dict[str, Any]) -> dict[str, Any]:
        """A rule's metrics are the approved metrics its glossary terms name, so they are never chosen separately."""
        term_ids, dataset_id = payload.get("glossary_term_ids"), payload.get("dataset_id")
        if not isinstance(term_ids, list) or not isinstance(dataset_id, int):
            return payload
        metric_ids = {
            link.metric_id
            for term_id in term_ids
            if isinstance(term_id, int)
            for link in self._term_links(term_id, dataset_id)
            if link.kind == "metric" and self._metric(link.metric_id) is not None
        }
        return {**payload, "metric_ids": sorted(metric_ids)}

    def _live_fingerprint(self, link: ExpertRuleLink) -> str | None:
        return self._fingerprint(link.kind, link.target_id, link.dataset_id)

    @staticmethod
    def _glossary_term_name(term_id: int) -> str:
        term = glossary_term_repository().get(term_id)
        return term.canonical_name if term else f"#{term_id}"

    @staticmethod
    def _column_name(column_id: int) -> str:
        column = column_dictionary_repository().get(column_id)
        return (column.display_name or column.column_name) if column else f"#{column_id}"

    @staticmethod
    def _physical_column(column_id: int) -> str | None:
        column = column_dictionary_repository().get(column_id)
        return column.column_name if column else None

    @expose("/expert-rules", methods=["GET"])
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_rules(self):
        """Every rule with its current revision and review state, for the administrator review page."""
        require_admin()
        user_name = user_names()
        rules = []
        rule_repository, link_repository = expert_rule_repository(), expert_rule_link_repository()
        for revision in self._review_revisions():
            rule = rule_repository.get(revision.rule_id)
            dataset = self._dataset(rule.dataset_id) if rule else None
            links = link_repository.for_revision(revision.id)
            metrics = getattr(dataset, "metrics", [])
            metric_names = {metric.id: metric.verbose_name or metric.metric_name for metric in metrics}
            column_ids = {condition["field_ref"]["column_dictionary_id"] for condition in revision.conditions}
            author_id = revision_author_id(db.session, revision)
            rules.append(
                {
                    **self._serialize(revision),
                    "dataset_id": rule.dataset_id if rule else None,
                    "dataset_name": getattr(dataset, "table_name", None),
                    "state": self._review_state(revision, links),
                    "column_names": {str(column_id): self._column_name(column_id) for column_id in column_ids},
                    "glossary_terms": [
                        {"id": link.target_id, "name": self._glossary_term_name(link.target_id)}
                        for link in links
                        if link.kind == "glossary"
                    ],
                    "metrics": [
                        {"id": link.target_id, "name": metric_names.get(link.target_id, f"#{link.target_id}")}
                        for link in links
                        if link.kind == "metric"
                    ],
                    "author_id": author_id,
                    "author_name": user_name(author_id),
                    "approver_name": user_name(revision.approver_id),
                    "approved_at": iso_datetime(revision.approved_at),
                    "revoker_name": user_name(revision.revoker_id),
                    "revoked_at": iso_datetime(revision.revoked_at),
                }
            )
        rules.sort(key=lambda item: item["name"].casefold())
        return self.response(
            200, rules=rules, current_user_id=current_user.id, require_second_reviewer=second_reviewer_required()
        )

    @expose("/expert-rules/options", methods=["GET"])
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def rule_options(self):
        """What a rule editor may reference per dataset: dictionary columns, approved glossary terms and metrics."""
        require_admin()
        terms_by_dataset: dict[int, list[dict[str, Any]]] = {}
        link_repository = glossary_term_link_repository()
        for revision in glossary_term_revision_repository().approved_current():
            links = link_repository.for_revision(revision.id)
            for dataset_id in {link.dataset_id for link in links}:
                dataset_links = [link for link in links if link.dataset_id == dataset_id]
                terms_by_dataset.setdefault(dataset_id, []).append(
                    {
                        "id": revision.term_id,
                        "name": self._glossary_term_name(revision.term_id),
                        # The editor shows the metrics a rule inherits and lists the term's own columns first.
                        "metric_ids": sorted(
                            link.metric_id
                            for link in dataset_links
                            if link.kind == "metric" and self._metric(link.metric_id) is not None
                        ),
                        "column_names": sorted(link.column_name for link in dataset_links if link.kind == "column"),
                    }
                )
        datasets = []
        column_repository = column_dictionary_repository()
        for dictionary in dataset_dictionary_repository().all():
            dataset = self._dataset(dictionary.id)
            if dataset is None or not can_access_dataset(dataset):
                continue
            columns = column_repository.list_for_dataset(dataset.id)
            datasets.append(
                {
                    "id": dataset.id,
                    "name": dataset.table_name,
                    "columns": [
                        {
                            "id": column.id,
                            "column_name": column.column_name,
                            "display_name": column.display_name,
                            "data_type": column.data_type,
                        }
                        for column in columns
                    ],
                    "glossary_terms": sorted(
                        terms_by_dataset.get(dataset.id, []), key=lambda term: term["name"].casefold()
                    ),
                    "metrics": [
                        {"id": metric.id, "name": metric.verbose_name or metric.metric_name}
                        for metric in getattr(dataset, "metrics", [])
                        if self._metric(metric.id) is not None
                    ],
                }
            )
        datasets.sort(key=lambda item: item["name"].casefold())
        return self.response(200, datasets=datasets)

    @expose("/expert-rules/discover", methods=["GET"])
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def discover(self):
        rules = []
        rule_repository, link_repository = expert_rule_repository(), expert_rule_link_repository()
        for revision in expert_rule_revision_repository().approved_current():
            rule = rule_repository.get(revision.rule_id)
            dataset = self._dataset(rule.dataset_id)
            if dataset is None or not can_access_dataset(dataset):
                continue
            links = link_repository.for_revision(revision.id)
            if not all(self._linked_target_authorized(link) for link in links):
                continue
            if rule_is_discoverable(revision, links, self._live_fingerprint):
                column_ids = {condition["field_ref"]["column_dictionary_id"] for condition in revision.conditions}
                rules.append(
                    {
                        **self._serialize(revision, redact=False),
                        # Let a consumer join a rule to catalog metrics and terms and read its conditions by
                        # column name.
                        "dataset_id": rule.dataset_id,
                        "metric_ids": sorted(link.target_id for link in links if link.kind == "metric"),
                        "glossary_term_ids": sorted(link.target_id for link in links if link.kind == "glossary"),
                        "column_names": {str(column_id): self._column_name(column_id) for column_id in column_ids},
                        # The physical column of each condition, so a consumer can filter a governed metric query by it.
                        "condition_columns": {
                            str(column_id): self._physical_column(column_id) for column_id in column_ids
                        },
                    }
                )
        return self.response(200, rules=rules)

    def _linked_target_authorized(self, link: ExpertRuleLink) -> bool:
        """Fail closed: any inaccessible or stale semantic target hides its rule."""
        dataset = self._dataset(link.dataset_id)
        if dataset is None or not can_access_dataset(dataset):
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
        return bool(dataset is not None and can_access_dataset(dataset))
