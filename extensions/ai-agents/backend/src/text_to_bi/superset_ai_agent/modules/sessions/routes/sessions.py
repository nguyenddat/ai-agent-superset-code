from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ....core.database import handle_errors, rollback_on_error
from ....core.security import csrf_protected
from ....migrations import ensure_agent_tables
from ...definitions.services.definitions import (
    definitions_on_dashboard,
    save_confirmed_definitions,
    serialize_definition,
)
from ...definitions.services.parsing import parse_clarification
from ..services.sessions import (
    delete_chat_session,
    recent_sessions,
    rename_chat_session,
    require_own_session,
    require_pending_clarification,
    serialize_session,
    session_turns,
)


@api(
    id="text_to_bi_chat_session_api",
    name="Superset AI Agent conversations API",
    description="Lists, reopens, renames and deletes the signed-in user's AI Agent conversations.",
    resource_name="sessions",
)
class AgentChatSessionAPI(RestApi):
    openapi_spec_tag = "Superset AI Agent"
    class_permission_name = "text_to_bi_chat_api"

    @expose("/", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_sessions(self):
        """The user's conversations, most recently active first."""
        ensure_agent_tables()
        return self.response(200, result=recent_sessions(int(current_user.id)))

    @expose("/<int:session_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_session(self, session_id: int):
        """One conversation with its turns in the order they were asked, and the user's definitions on its dashboard."""
        ensure_agent_tables()
        user_id = int(current_user.id)
        chat_session = require_own_session(session_id, user_id)
        definitions = definitions_on_dashboard(user_id, chat_session.dashboard_id)
        result = {
            **serialize_session(chat_session),
            "turns": session_turns(session_id),
            "definitions": [serialize_definition(item) for item in definitions],
        }
        return self.response(200, result=result)

    @expose("/<int:session_id>/questions/<int:question_id>/clarification", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def answer_clarification(self, session_id: int, question_id: int):
        """The user's answer to the definitions a question asked them to confirm.

        `{"state": "confirmed", "definitions": [...]}` keeps what the user chose for every conversation they have about
        the dashboard; `{"state": "dismissed"}` keeps nothing.
        """
        ensure_agent_tables()
        user_id = int(current_user.id)
        chat_session = require_own_session(session_id, user_id)
        question = require_pending_clarification(question_id, session_id)
        state, confirmed = parse_clarification(request.get_json(silent=True))
        save_confirmed_definitions(
            confirmed, user_id=user_id, dashboard_id=chat_session.dashboard_id, question_id=question_id,
            session_id=session_id, cookie_header=request.headers.get("Cookie", ""),
        )
        question.clarification_state = state
        db.session.commit()
        definitions = definitions_on_dashboard(user_id, chat_session.dashboard_id)
        return self.response(200, result=[serialize_definition(item) for item in definitions])

    @expose("/<int:session_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def rename_session(self, session_id: int):
        """Rename a conversation."""
        ensure_agent_tables()
        chat_session = require_own_session(session_id, int(current_user.id))
        rename_chat_session(chat_session, (request.get_json(silent=True) or {}).get("title"))
        db.session.commit()
        return self.response(200, result=serialize_session(chat_session))

    @expose("/<int:session_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_session(self, session_id: int):
        """Delete a conversation; its questions stay in the log, and the user's definitions stay for the dashboard."""
        ensure_agent_tables()
        delete_chat_session(require_own_session(session_id, int(current_user.id)))
        db.session.commit()
        return self.response(200, message="Đã xoá cuộc trò chuyện.")
