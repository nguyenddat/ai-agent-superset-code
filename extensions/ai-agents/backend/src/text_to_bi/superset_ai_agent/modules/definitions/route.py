from datetime import datetime, timezone

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_appbuilder.security.sqla.models import User
from flask_login import current_user
from superset import db
from superset.models.dashboard import Dashboard
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ...models.question_log import AgentQuestion, AgentUserDefinition, ensure_question_tables
from .parsing import DefinitionError, parse_definition

# How administrators settled a user's own definition: a shared business term or rule now covers the concept
# (`promoted`), or it stays the user's personal sense (`ignored`). Shared rules carry the business's own thresholds,
# set by its experts; a user's threshold is only a signal of what people ask about.
REVIEW_STATUSES = ("pending", "promoted", "ignored")
MAX_REVIEW_IDS = 200


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None


def _is_admin() -> bool:
    return bool(current_user and current_user.is_authenticated and any(
        role.name == "Admin" for role in getattr(current_user, "roles", [])
    ))


def _valid_csrf() -> bool:
    from flask_wtf.csrf import validate_csrf
    from wtforms import ValidationError

    try:
        validate_csrf(request.headers.get("X-CSRFToken"))
    except ValidationError:
        return False
    return True


def user_definitions(user_id: int, dashboard_id: int) -> list[AgentUserDefinition]:
    """What one user confirmed concepts mean on one dashboard, oldest first."""
    ensure_question_tables(db.engine)
    return (
        db.session.query(AgentUserDefinition)
        .filter(AgentUserDefinition.user_id == user_id, AgentUserDefinition.dashboard_id == dashboard_id)
        .order_by(AgentUserDefinition.id)
        .all()
    )


def serialize_definition(definition: AgentUserDefinition) -> dict:
    return {
        "id": definition.id,
        "kind": definition.kind,
        "name": definition.name,
        "concept": definition.concept,
        "definition": definition.definition,
        "dashboard_id": definition.dashboard_id,
        "source_question_id": definition.source_question_id,
        "review_status": definition.review_status,
        "updated_on": _isoformat(definition.updated_on),
    }


def _user_name(user: User | None) -> str | None:
    if user is None:
        return None
    return " ".join(part for part in (user.first_name, user.last_name) if part) or user.username


def _serialize_for_review(
    definition: AgentUserDefinition, users: dict[int, User], dashboards: dict[int, str], questions: dict[int, str],
) -> dict:
    return {
        **serialize_definition(definition),
        "user_id": definition.user_id,
        "defined_by": _user_name(users.get(definition.user_id)),
        "dashboard_title": dashboards.get(definition.dashboard_id),
        "question": questions.get(definition.source_question_id),
        "reviewed_by": _user_name(users.get(definition.reviewed_by)),
        "reviewed_on": _isoformat(definition.reviewed_on),
    }


@api(
    id="text_to_bi_user_definition_api",
    name="Superset AI Agent user definitions API",
    description="The signed-in user's own definitions of business concepts, and their review by administrators.",
    resource_name="definitions",
)
class AgentUserDefinitionAPI(RestApi):
    openapi_spec_tag = "Superset AI Agent"
    class_permission_name = "text_to_bi_chat_api"

    @staticmethod
    def _own_definition(definition_id: int) -> AgentUserDefinition | None:
        ensure_question_tables(db.engine)
        return db.session.query(AgentUserDefinition).filter_by(
            id=definition_id, user_id=int(current_user.id),
        ).one_or_none()

    @expose("/", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def list_own(self):
        """The user's definitions on `?dashboard_id=`, shared by all their conversations about that dashboard."""
        dashboard_id = request.args.get("dashboard_id", type=int)
        if dashboard_id is None:
            return self.response_400(message="Cần dashboard_id.")
        definitions = user_definitions(int(current_user.id), dashboard_id)
        return self.response(200, result=[serialize_definition(item) for item in definitions])

    @expose("/<int:definition_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    def update_own(self, definition_id: int):
        """Change what the user's definition says; administrators see it again as not yet reviewed."""
        if not _valid_csrf():
            return self.response(403, message="CSRF token không hợp lệ.")
        definition = self._own_definition(definition_id)
        if definition is None:
            return self.response_404()
        try:
            item = parse_definition({**(request.get_json(silent=True) or {}), "kind": definition.kind})
        except DefinitionError as ex:
            return self.response_400(message=str(ex))
        definition.name = item["name"]
        definition.concept = item["concept"] or definition.concept
        definition.definition = item["definition"]
        definition.review_status = "pending"
        definition.reviewed_by = None
        definition.reviewed_on = None
        definition.updated_on = datetime.now(timezone.utc)
        db.session.commit()
        return self.response(200, result=serialize_definition(definition))

    @expose("/<int:definition_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    def delete_own(self, definition_id: int):
        """Forget the user's definition; the agent asks about the concept again."""
        if not _valid_csrf():
            return self.response(403, message="CSRF token không hợp lệ.")
        definition = self._own_definition(definition_id)
        if definition is None:
            return self.response_404()
        db.session.delete(definition)
        db.session.commit()
        return self.response(200, message="Đã xoá định nghĩa.")

    @expose("/review", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def list_review(self):
        """Every user's definitions, most recently changed first (admin only)."""
        if not _is_admin():
            return self.response(403, message="Admin access required.")
        ensure_question_tables(db.engine)
        definitions = (
            db.session.query(AgentUserDefinition)
            .order_by(AgentUserDefinition.updated_on.desc(), AgentUserDefinition.id.desc())
            .all()
        )
        user_ids = ({item.user_id for item in definitions} | {item.reviewed_by for item in definitions}) - {None}
        users = {user.id: user for user in db.session.query(User).filter(User.id.in_(user_ids))}
        dashboard_ids = {item.dashboard_id for item in definitions}
        dashboards = dict(
            db.session.query(Dashboard.id, Dashboard.dashboard_title).filter(Dashboard.id.in_(dashboard_ids))
        )
        question_ids = {item.source_question_id for item in definitions} - {None}
        questions = {
            question_id: rewritten or question
            for question_id, question, rewritten in db.session.query(
                AgentQuestion.id, AgentQuestion.question, AgentQuestion.rewritten_question,
            ).filter(AgentQuestion.id.in_(question_ids))
        }
        return self.response(
            200, definitions=[_serialize_for_review(item, users, dashboards, questions) for item in definitions],
        )

    @expose("/review", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    def set_review(self):
        """Record `{ids, status}`: a shared term or rule now covers the concept, it stays personal, or is reopened."""
        if not _is_admin():
            return self.response(403, message="Admin access required.")
        if not _valid_csrf():
            return self.response(403, message="CSRF token không hợp lệ.")
        body = request.get_json(silent=True) or {}
        ids, status = body.get("ids"), body.get("status")
        if status not in REVIEW_STATUSES:
            return self.response_400(message="Trạng thái phải là pending, promoted hoặc ignored.")
        valid_ids = isinstance(ids, list) and 0 < len(ids) <= MAX_REVIEW_IDS and all(
            isinstance(item, int) and not isinstance(item, bool) for item in ids
        )
        if not valid_ids:
            return self.response_400(message=f"Cần từ 1 đến {MAX_REVIEW_IDS} id định nghĩa.")
        ensure_question_tables(db.engine)
        reviewed = status != "pending"
        updated = db.session.query(AgentUserDefinition).filter(AgentUserDefinition.id.in_(ids)).update(
            {
                AgentUserDefinition.review_status: status,
                AgentUserDefinition.reviewed_by: int(current_user.id) if reviewed else None,
                AgentUserDefinition.reviewed_on: datetime.now(timezone.utc) if reviewed else None,
            },
            synchronize_session=False,
        )
        db.session.commit()
        return self.response(200, updated=updated)
