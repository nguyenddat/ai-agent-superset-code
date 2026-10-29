import logging
import time
from datetime import datetime, timedelta, timezone

from flask import Response, request, stream_with_context
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ....common.exceptions import AgentError
from ....common.utils.type_formatter import sse_event
from ....core.chat_models import get_chat_model
from ....core.database import handle_errors, rollback_on_error
from ....core.security import csrf_protected
from ....migrations import ensure_agent_tables
from ...definitions.services.definitions import definitions_for_agent
from ...semantic_layer.services.catalog import cached_semantic_catalog
from ...semantic_layer.services.data_model import cached_data_model_sources, propose_agent_dataset
from ...semantic_layer.services.metrics import create_agent_metric, run_metric_query
from ...sessions.services.sessions import require_own_session, start_session, touch_session
from ...superset.services.dashboards import require_dashboard_access
from ..services.conversation import asked_question, log_question, parse_chat_request, record_tool_call, session_history
from ..services.pipeline import AgentOutcome, MetricBuilder, run_agent

logger = logging.getLogger(__name__)
# "Hôm nay" and "tuần này" are read in Vietnam's time, whatever the server's clock zone.
BUSINESS_TIMEZONE = timezone(timedelta(hours=7))
FAILED_ANSWER_MESSAGE = "AI Agent không hoàn tất được câu trả lời."


@api(
    id="text_to_bi_chat_api",
    name="Superset AI Agent API",
    description="Streaming semantic resolution API for the Superset AI Agent extension.",
    resource_name="chat",
)
class TextToBIAgentAPI(RestApi):
    openapi_spec_tag = "Superset AI Agent"
    class_permission_name = "text_to_bi_chat_api"

    @expose("/stream", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def stream_chat(self):
        """Answer one question in a conversation; without `session_id` it starts one about `dashboard_id`.

        With `retry_of`, the conversation's earlier question is answered again, after the user confirmed definitions.
        The reply streams as SSE: `session` first, then each step as a tool call, the answer, and `done`, which carries
        the definitions the user is asked to confirm.
        """
        asked = parse_chat_request(request.get_json(silent=True))
        user_id = int(current_user.id)
        ensure_agent_tables()
        session_id, retry_of = asked["session_id"], asked["retry_of"]
        chat_session = require_own_session(session_id, user_id) if session_id is not None else None
        question = asked_question(asked["question"], session_id, retry_of)
        dashboard_id = chat_session.dashboard_id if chat_session else asked["dashboard_id"]
        require_dashboard_access(dashboard_id)
        if chat_session is None:
            chat_session = start_session(user_id, dashboard_id, question)
            db.session.commit()
        session_payload = {"id": chat_session.id, "title": chat_session.title, "dashboard_id": dashboard_id}
        session_id = chat_session.id
        history = session_history(session_id, retry_of)
        user_definitions = definitions_for_agent(user_id, dashboard_id)
        # The Semantic Layer is read and its metrics run as this user, so forward their session and CSRF token.
        cookie_header = request.headers.get("Cookie", "")
        csrf_token = request.headers.get("X-CSRFToken", "")

        @stream_with_context
        def events():
            started = time.monotonic()
            outcome = AgentOutcome()
            tool_calls: list[dict] = []
            error = None
            yield sse_event("session", session_payload)
            try:
                pipeline = run_agent(
                    question, history, get_chat_model(), lambda: cached_semantic_catalog(user_id, cookie_header),
                    user_definitions,
                    run_metric=lambda dataset_id, metric_id, query: run_metric_query(
                        dataset_id, metric_id, query, cookie_header, csrf_token,
                    ),
                    today=datetime.now(BUSINESS_TIMEZONE).date(),
                    builder=MetricBuilder(
                        load_sources=lambda: cached_data_model_sources(user_id, cookie_header),
                        create_metric=lambda draft: create_agent_metric(draft, cookie_header, csrf_token),
                        propose_dataset=lambda draft: propose_agent_dataset(draft, cookie_header, csrf_token),
                    ),
                )
                while True:
                    try:
                        name, data = next(pipeline)
                    except StopIteration as finished:
                        outcome = finished.value
                        break
                    record_tool_call(tool_calls, name, data)
                    yield sse_event(name, data)
            except AgentError as agent_error:
                error = str(agent_error)
                yield sse_event("error", {"message": error})
            except Exception as unexpected:
                logger.exception("AI Agent stream failed")
                error = str(unexpected) or type(unexpected).__name__
                yield sse_event("error", {"message": FAILED_ANSWER_MESSAGE})
            # The log is written after the answer streamed; a failed write is logged and never breaks the answer.
            try:
                question_id = log_question(
                    user_id=user_id, session_id=session_id, dashboard_id=dashboard_id, question=question,
                    history_turns=len(history) // 2, outcome=outcome, tool_calls=tool_calls, retry_of=retry_of,
                    started=started, error=error,
                ).id
                touch_session(session_id)
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.exception("Could not record the AI Agent question")
                question_id = None
            yield sse_event("done", {
                "question_id": question_id,
                "status": "failed" if error else outcome.status,
                "missing": [] if error else outcome.missing,
                "clarifications": [] if error or question_id is None else outcome.clarifications,
                "user_definitions": [] if error else outcome.user_definitions,
                "result": None if error else outcome.result,
                "query_error": None if error else outcome.query_error,
            })

        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return Response(events(), mimetype="text/event-stream", headers=headers)
