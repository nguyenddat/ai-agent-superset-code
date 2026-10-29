from datetime import datetime, timezone
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_appbuilder.security.sqla.models import User
from flask_login import current_user
from superset import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ...models.question_log import AgentQuestion, AgentQuestionHandling, ensure_question_tables
from ..access import is_admin
from .handling import HANDLING_STATUSES, HandlingError, count_by_handling, parse_handling

REVIEW_LIST_LIMIT = 200


def _user_name(user: User | None) -> str | None:
    if user is None:
        return None
    return " ".join(part for part in (user.first_name, user.last_name) if part) or user.username


def _serialize(question: AgentQuestion, handling: AgentQuestionHandling | None, users: dict[int, User]) -> dict:
    return {
        "id": question.id,
        "question": question.question,
        "rewritten_question": question.rewritten_question,
        "asked_by": _user_name(users.get(question.user_id)),
        "asked_on": question.created_on.isoformat() if question.created_on else None,
        "glossary_terms": question.glossary_terms,
        "metrics": question.metrics,
        "expert_rules": question.expert_rules,
        "missing": question.missing,
        "requires_expert_rule": question.requires_expert_rule,
        "suggestions": question.suggestions or {},
        "handling": {
            "status": handling.status if handling else "pending",
            "note": handling.note if handling else None,
            "handled_by": _user_name(users.get(handling.handled_by)) if handling else None,
            "handled_on": handling.handled_on.isoformat() if handling and handling.handled_on else None,
        },
    }


@api(
    id="text_to_bi_question_api",
    name="Superset AI Agent question review API",
    description="Lists the questions AI Agent could not fully resolve and records how administrators handled them.",
    resource_name="questions",
)
class AgentQuestionReviewAPI(RestApi):
    openapi_spec_tag = "Superset AI Agent"
    class_permission_name = "text_to_bi_chat_api"

    def _users(self, user_ids: set[int | None]) -> dict[int, User]:
        known_ids = [user_id for user_id in user_ids if user_id is not None]
        if not known_ids:
            return {}
        return {user.id: user for user in db.session.query(User).filter(User.id.in_(known_ids))}

    @expose("/review", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def list_review(self):
        """The `needs_review` questions, newest first, with their handling.

        `?handling=` narrows to one handling status and `?missing=metric` to the questions missing that kind.
        """
        if not is_admin():
            return self.response(403, message="Admin access required.")
        handling_filter = request.args.get("handling", "all")
        if handling_filter not in ("all", *HANDLING_STATUSES):
            return self.response_400(message="Bộ lọc xử lý không hợp lệ.")
        missing_filter = request.args.get("missing")
        if missing_filter not in (None, "glossary", "metric", "expert_rule"):
            return self.response_400(message="Bộ lọc phần thiếu không hợp lệ.")
        ensure_question_tables(db.engine)
        rows = (
            db.session.query(AgentQuestion, AgentQuestionHandling)
            .outerjoin(AgentQuestionHandling, AgentQuestionHandling.question_id == AgentQuestion.id)
            .filter(AgentQuestion.status == "needs_review")
            .order_by(AgentQuestion.created_on.desc())
            .all()
        )
        if missing_filter:
            rows = [(question, handling) for question, handling in rows if missing_filter in (question.missing or [])]
        counts = count_by_handling([handling.status if handling else None for _, handling in rows])
        if handling_filter != "all":
            rows = [(question, handling) for question, handling in rows
                    if (handling.status if handling else "pending") == handling_filter]
        rows = rows[:REVIEW_LIST_LIMIT]
        users = self._users({question.user_id for question, _ in rows} | {
            handling.handled_by for _, handling in rows if handling
        })
        return self.response(
            200,
            counts=counts,
            questions=[_serialize(question, handling, users) for question, handling in rows],
        )

    @expose("/<int:question_id>/handling", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    def set_handling(self, question_id: int):
        """Record how a question was handled; `pending` removes the decision."""
        from flask_wtf.csrf import validate_csrf
        from wtforms import ValidationError

        if not is_admin():
            return self.response(403, message="Admin access required.")
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return self.response(403, message="CSRF token không hợp lệ.")
        try:
            status, note = parse_handling(request.get_json(silent=True))
        except HandlingError as ex:
            return self.response_400(message=str(ex))
        ensure_question_tables(db.engine)
        question = db.session.get(AgentQuestion, question_id)
        if question is None or question.status != "needs_review":
            return self.response_404()
        handling = db.session.get(AgentQuestionHandling, question_id)
        if status == "pending":
            if handling is not None:
                db.session.delete(handling)
            handling = None
        else:
            if handling is None:
                handling = AgentQuestionHandling(question_id=question_id)
                db.session.add(handling)
            handling.status = status
            handling.note = note
            handling.handled_by = int(current_user.id)
            handling.handled_on = datetime.now(timezone.utc)
        db.session.commit()
        users: dict[int, Any] = self._users({question.user_id, handling.handled_by if handling else None})
        return self.response(200, question=_serialize(question, handling, users))
