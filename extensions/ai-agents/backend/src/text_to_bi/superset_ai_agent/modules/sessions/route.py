from datetime import datetime, timezone

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset.models.dashboard import Dashboard
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ...models.question_log import AgentChatSession, AgentQuestion, AgentUserDefinition, ensure_question_tables
from ..access import valid_csrf
from ..definitions.conditions import conditions_for
from ..definitions.parsing import DefinitionError, parse_definitions
from ..definitions.route import serialize_definition, user_definitions

SESSION_LIST_LIMIT = 200
MAX_TITLE_LENGTH = 200
# What the chat showed for a turn that failed; the stored error is the internal cause, kept for the log.
FAILED_TURN_MESSAGE = "AI Agent không hoàn tất được câu trả lời."


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None


def _dashboard_titles(dashboard_ids: set[int]) -> dict[int, str]:
    if not dashboard_ids:
        return {}
    rows = db.session.query(Dashboard.id, Dashboard.dashboard_title).filter(Dashboard.id.in_(dashboard_ids))
    return {dashboard_id: title for dashboard_id, title in rows}


def _serialize_session(chat_session: AgentChatSession, dashboard_titles: dict[int, str]) -> dict:
    return {
        "id": chat_session.id,
        "title": chat_session.title,
        "dashboard_id": chat_session.dashboard_id,
        "dashboard_title": dashboard_titles.get(chat_session.dashboard_id),
        "created_on": _isoformat(chat_session.created_on),
        "updated_on": _isoformat(chat_session.updated_on),
    }


def _serialize_turn(question: AgentQuestion) -> dict:
    return {
        "id": question.id,
        "question": question.question,
        "answer": question.answer or "",
        "tool_calls": question.tool_calls or [],
        "status": question.status,
        "missing": question.missing or [],
        "error": FAILED_TURN_MESSAGE if question.error else None,
        "clarifications": question.clarifications or [],
        "clarification_state": question.clarification_state,
        "retry_of": question.retry_of,
        "result": question.query_result,
        "asked_on": _isoformat(question.created_on),
    }



@api(
    id="text_to_bi_chat_session_api",
    name="Superset AI Agent conversations API",
    description="Lists, reopens, renames and deletes the signed-in user's AI Agent conversations.",
    resource_name="sessions",
)
class AgentChatSessionAPI(RestApi):
    openapi_spec_tag = "Superset AI Agent"
    class_permission_name = "text_to_bi_chat_api"

    @staticmethod
    def _own_session(session_id: int) -> AgentChatSession | None:
        ensure_question_tables(db.engine)
        return db.session.query(AgentChatSession).filter_by(id=session_id, user_id=int(current_user.id)).one_or_none()

    @expose("/", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def list_sessions(self):
        """The user's conversations, most recently active first."""
        ensure_question_tables(db.engine)
        sessions = (
            db.session.query(AgentChatSession)
            .filter(AgentChatSession.user_id == int(current_user.id))
            .order_by(AgentChatSession.updated_on.desc(), AgentChatSession.id.desc())
            .limit(SESSION_LIST_LIMIT)
            .all()
        )
        titles = _dashboard_titles({chat_session.dashboard_id for chat_session in sessions})
        return self.response(200, result=[_serialize_session(chat_session, titles) for chat_session in sessions])

    @expose("/<int:session_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_session(self, session_id: int):
        """One conversation with its turns in the order they were asked."""
        chat_session = self._own_session(session_id)
        if chat_session is None:
            return self.response_404()
        questions = (
            db.session.query(AgentQuestion)
            .filter(AgentQuestion.session_id == session_id)
            .order_by(AgentQuestion.id)
            .all()
        )
        titles = _dashboard_titles({chat_session.dashboard_id})
        result = {
            **_serialize_session(chat_session, titles),
            "turns": [_serialize_turn(item) for item in questions],
            "definitions": [
                serialize_definition(item)
                for item in user_definitions(int(current_user.id), chat_session.dashboard_id)
            ],
        }
        return self.response(200, result=result)

    @expose("/<int:session_id>/questions/<int:question_id>/clarification", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    def answer_clarification(self, session_id: int, question_id: int):
        """The user's answer to the definitions a question asked them to confirm.

        `{"state": "confirmed", "definitions": [...]}` keeps what the user chose for every conversation they have about
        the dashboard; `{"state": "dismissed"}` keeps nothing.
        """
        if not valid_csrf():
            return self.response(403, message="CSRF token không hợp lệ.")
        chat_session = self._own_session(session_id)
        if chat_session is None:
            return self.response_404()
        question = db.session.query(AgentQuestion).filter_by(id=question_id, session_id=session_id).one_or_none()
        if question is None or question.clarification_state != "pending":
            return self.response_404()
        body = request.get_json(silent=True) or {}
        state = body.get("state")
        if state not in ("confirmed", "dismissed"):
            return self.response_400(message="Trạng thái phải là confirmed hoặc dismissed.")
        try:
            confirmed = parse_definitions(body.get("definitions")) if state == "confirmed" else []
        except DefinitionError as ex:
            return self.response_400(message=str(ex))
        user_id = int(current_user.id)
        # Confirming a concept again replaces what the user said about it before on this dashboard.
        definitions = user_definitions(user_id, chat_session.dashboard_id)
        existing = {(item.kind, item.name.casefold()): item for item in definitions}
        now = datetime.now(timezone.utc)
        conditions = conditions_for(confirmed, user_id, request.headers.get("Cookie", ""))
        for item, item_conditions in zip(confirmed, conditions):
            definition = existing.get((item["kind"], item["name"].casefold()))
            if definition is None:
                definition = AgentUserDefinition(user_id=user_id, dashboard_id=chat_session.dashboard_id)
                definition.kind = item["kind"]
                db.session.add(definition)
            definition.name = item["name"]
            definition.concept = item["concept"]
            definition.definition = item["definition"]
            definition.conditions = item_conditions
            definition.source_question_id = question_id
            definition.source_session_id = session_id
            definition.review_status = "pending"
            definition.reviewed_by = None
            definition.reviewed_on = None
            definition.updated_on = now
        question.clarification_state = state
        db.session.commit()
        definitions = user_definitions(user_id, chat_session.dashboard_id)
        return self.response(200, result=[serialize_definition(item) for item in definitions])

    @expose("/<int:session_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    def rename_session(self, session_id: int):
        """Rename a conversation."""
        if not valid_csrf():
            return self.response(403, message="CSRF token không hợp lệ.")
        chat_session = self._own_session(session_id)
        if chat_session is None:
            return self.response_404()
        title = (request.get_json(silent=True) or {}).get("title")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > MAX_TITLE_LENGTH:
            return self.response_400(message="Tên cuộc trò chuyện phải là chuỗi không rỗng, tối đa 200 ký tự.")
        chat_session.title = title.strip()
        db.session.commit()
        titles = _dashboard_titles({chat_session.dashboard_id})
        return self.response(200, result=_serialize_session(chat_session, titles))

    @expose("/<int:session_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    def delete_session(self, session_id: int):
        """Delete a conversation; its questions stay in the log, and the user's definitions stay for the dashboard."""
        if not valid_csrf():
            return self.response(403, message="CSRF token không hợp lệ.")
        chat_session = self._own_session(session_id)
        if chat_session is None:
            return self.response_404()
        db.session.query(AgentQuestion).filter(AgentQuestion.session_id == session_id).update(
            {AgentQuestion.session_id: None}
        )
        db.session.delete(chat_session)
        db.session.commit()
        return self.response(200, message="Đã xoá cuộc trò chuyện.")
