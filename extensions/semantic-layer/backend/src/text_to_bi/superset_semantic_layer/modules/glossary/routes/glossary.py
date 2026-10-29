from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db, security_manager

from ....common.utils.type_formatter import iso_datetime
from ....core.database import handle_errors, rollback_on_error
from ....core.security import csrf_protected, require_admin, second_reviewer_required
from ....migrations import ensure_dictionary_tables
from ...superset.services.datasets import datasets_by_name, get_dataset, is_internal_dataset
from ...superset.services.users import user_names
from ..dependencies import (
    glossary_term_audit_event_repository,
    glossary_term_repository,
    glossary_term_revision_repository,
)
from ..exceptions import GlossaryTermNotFoundError
from ..models import GlossaryTerm, GlossaryTermLink, GlossaryTermRevision
from ..services.discovery import (
    discoverable_glossary_terms,
    glossary_link_target,
    glossary_links,
    glossary_metric_approved,
)
from ..services.glossary import (
    GlossaryValidationError,
    approve_revision,
    create_draft,
    glossary_link_fingerprint,
    revision_author_id,
    revoke_revision,
    update_draft,
)


class GlossaryRoutes:
    """Routes of SemanticLayerAPI. The Business Glossary: governed terms, their lifecycle and discovery."""

    @staticmethod
    def _glossary_revision(revision: GlossaryTermRevision, links: list[GlossaryTermLink]) -> dict[str, Any]:
        return {
            "id": revision.id,
            "term_id": revision.term_id,
            "revision_number": revision.revision_number,
            "canonical_name": revision.term.canonical_name,
            "definition": revision.definition,
            "synonyms": revision.synonyms or [],
            "provenance": revision.provenance,
            "status": revision.status,
            "is_current": revision.is_current,
            "created_at": iso_datetime(revision.created_on),
            "approved_at": iso_datetime(revision.approved_at),
            "revoked_at": iso_datetime(revision.revoked_at),
            "links": [
                {
                    "kind": link.kind,
                    "dataset_id": link.dataset_id,
                    "column_name": link.column_name,
                    "metric_id": link.metric_id,
                }
                for link in links
            ],
        }

    def _glossary_term(self, term: GlossaryTerm, revisions: list[GlossaryTermRevision]) -> dict[str, Any]:
        serialized = [self._glossary_revision(revision, glossary_links(revision.id)) for revision in revisions]
        current = next((revision for revision in serialized if revision["is_current"]), None)
        return {
            "id": term.id,
            "canonical_name": term.canonical_name,
            "owner_id": term.owner_id,
            "steward_id": term.steward_id,
            "current_revision": current,
            "revisions": serialized,
        }

    def _glossary_term_by_id(self, term_id: int) -> GlossaryTerm | None:
        return glossary_term_repository().get(term_id)

    @staticmethod
    def _glossary_user_exists(user_id: int) -> bool:
        return security_manager.get_user_by_id(user_id) is not None

    def _glossary_link_is_live(self, link: GlossaryTermLink) -> bool:
        """The linked object is unchanged since the term was saved, and a linked metric is still approved."""
        if self._glossary_live_fingerprint(link) != link.fingerprint:
            return False
        if link.kind != "metric":
            return True
        dataset = get_dataset(link.dataset_id)
        return glossary_metric_approved(dataset, glossary_link_target(link, dataset))

    def _glossary_live_fingerprint(self, link: GlossaryTermLink) -> str | None:
        dataset = get_dataset(link.dataset_id)
        if dataset is None:
            return None
        target = glossary_link_target(link, dataset)
        if link.kind != "dataset" and target is None:
            return None
        return glossary_link_fingerprint(dataset, link.kind, target)

    def _glossary_review_entry(self, term: GlossaryTerm, revision: GlossaryTermRevision, user_name: Any) -> dict:
        """A term's current revision with its review state, the people behind it and readable link labels."""
        links = glossary_links(revision.id)
        entry = self._glossary_term(term, [revision])
        stale = not all(self._glossary_link_is_live(link) for link in links)
        author_id = revision_author_id(db.session, revision)
        current = entry["current_revision"]
        for serialized, link in zip(current["links"], links):
            dataset = get_dataset(link.dataset_id)
            target = glossary_link_target(link, dataset) if dataset else None
            serialized["dataset_name"] = dataset.table_name if dataset else None
            if link.kind == "dataset":
                serialized["target_name"] = None
            else:
                fallback = link.column_name if link.kind == "column" else getattr(target, "metric_name", None)
                serialized["target_name"] = getattr(target, "verbose_name", None) or fallback
        return {
            **entry,
            "state": "outdated" if revision.status == "approved" and stale else revision.status,
            "author_id": author_id,
            "author_name": user_name(author_id),
            "approver_name": user_name(revision.approver_id),
            "revoker_name": user_name(revision.revoker_id),
        }

    @expose("/glossary", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_glossary(self):
        require_admin()
        ensure_dictionary_tables()
        user_name = user_names()
        terms = []
        revision_repository = glossary_term_revision_repository()
        for term in glossary_term_repository().by_canonical_name():
            revision = revision_repository.current_for(term.id)
            if revision is not None:
                terms.append(self._glossary_review_entry(term, revision, user_name))
        return self.response(
            200,
            terms=terms,
            current_user_id=current_user.id,
            require_second_reviewer=second_reviewer_required(),
        )

    @expose("/glossary/options", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def glossary_options(self):
        """What a term may link to: each dataset with its physical active columns and its saved metrics."""
        require_admin()
        datasets = []
        for dataset in datasets_by_name():
            if is_internal_dataset(dataset):
                continue
            datasets.append(
                {
                    "id": dataset.id,
                    "name": dataset.table_name,
                    "columns": [
                        {"column_name": column.column_name, "name": column.verbose_name or column.column_name}
                        for column in dataset.columns
                        if column.is_active is True and not column.expression
                    ],
                    # A term builds on approved metrics only, so a metric must pass review before a term can name it.
                    "metrics": [
                        {"id": metric.id, "name": metric.verbose_name or metric.metric_name}
                        for metric in dataset.metrics
                        if glossary_metric_approved(dataset, metric)
                    ],
                }
            )
        datasets.sort(key=lambda item: item["name"].casefold())
        return self.response(200, datasets=datasets)

    @expose("/glossary/<int:term_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_glossary(self, term_id: int):
        require_admin()
        ensure_dictionary_tables()
        term = self._glossary_term_by_id(term_id)
        if term is None:
            raise GlossaryTermNotFoundError()
        revisions = glossary_term_revision_repository().for_term(term_id)
        return self.response(200, term=self._glossary_term(term, revisions))

    @expose("/glossary", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_glossary(self):
        require_admin()
        ensure_dictionary_tables()
        revision = create_draft(
            db.session,
            request.get_json(silent=True),
            current_user.id,
            get_dataset,
            self._glossary_user_exists,
            glossary_metric_approved,
        )
        db.session.commit()
        return self.response(201, term=self._glossary_term(revision.term, [revision]))

    @expose("/glossary/<int:term_id>/draft", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_glossary_draft(self, term_id: int):
        require_admin()
        ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        current = glossary_term_revision_repository().current_for(term_id)
        if current is None:
            raise GlossaryTermNotFoundError()
        expected_revision = payload.get("expected_revision") if isinstance(payload, dict) else None
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise GlossaryValidationError("expected_revision is required.")
        content = dict(payload)
        content.pop("expected_revision")
        revision = update_draft(
            db.session,
            current,
            content,
            expected_revision,
            current_user.id,
            get_dataset,
            self._glossary_user_exists,
            glossary_metric_approved,
        )
        db.session.commit()
        return self.response(200, term=self._glossary_term(revision.term, [revision]))

    def _glossary_lifecycle(self, term_id: int, event: str, expected_revision: int, actor_id: int, reason: str | None):
        ensure_dictionary_tables()
        revision = glossary_term_revision_repository().current_for(term_id)
        if revision is None:
            raise GlossaryTermNotFoundError()
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise GlossaryValidationError("expected_revision is required.")
        if event == "approve":
            approve_revision(db.session, revision, expected_revision, actor_id, reason, second_reviewer_required())
        else:
            revoke_revision(db.session, revision, expected_revision, actor_id, reason)
        db.session.commit()
        return self.response(200, term=self._glossary_term(revision.term, [revision]))

    @expose("/glossary/<int:term_id>/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve_glossary(self, term_id: int):
        require_admin()
        payload = request.get_json(silent=True)
        expected_revision = payload.get("expected_revision") if isinstance(payload, dict) else None
        reason = payload.get("reason") if isinstance(payload, dict) else None
        return self._glossary_lifecycle(term_id, "approve", expected_revision, current_user.id, reason)

    @expose("/glossary/<int:term_id>/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke_glossary(self, term_id: int):
        require_admin()
        payload = request.get_json(silent=True)
        expected_revision = payload.get("expected_revision") if isinstance(payload, dict) else None
        reason = payload.get("reason") if isinstance(payload, dict) else None
        return self._glossary_lifecycle(term_id, "revoke", expected_revision, current_user.id, reason)

    @expose("/glossary/<int:term_id>/audit", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def glossary_audit(self, term_id: int):
        require_admin()
        ensure_dictionary_tables()
        events = glossary_term_audit_event_repository().for_term(term_id)
        user_name = user_names()
        return self.response(
            200,
            events=[
                {
                    "id": row.id,
                    "action": row.event_type,
                    "revision_number": row.revision_number,
                    "actor_id": row.actor_id,
                    "actor_name": user_name(row.actor_id),
                    "reason": row.reason,
                    "created_at": row.occurred_at.isoformat(),
                }
                for row in events
            ],
        )

    @expose("/glossary/discovery", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def glossary_discovery(self):
        """Return only approved, current, fresh links to caller-authorized datasets."""
        ensure_dictionary_tables()
        return self.response(200, terms=discoverable_glossary_terms())

