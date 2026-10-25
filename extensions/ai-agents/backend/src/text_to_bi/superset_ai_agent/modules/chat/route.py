import json
import logging
import time
from datetime import datetime, timedelta, timezone

from flask import Response, request, stream_with_context
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset.commands.dashboard.exceptions import DashboardAccessDeniedError, DashboardNotFoundError
from superset.daos.dashboard import DashboardDAO
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ...core.chat_models import get_chat_model
from ...models.question_log import AgentChatSession, AgentQuestion, ensure_question_tables
from ..definitions.route import user_definitions
from .pipeline import MAX_HISTORY_TURNS, AgentOutcome, MetricBuilder, recent_history, run_agent
from .semantic_source import (
    SemanticSourceError,
    cached_data_model_sources,
    cached_semantic_catalog,
    create_agent_metric,
    propose_agent_dataset,
    run_metric_query,
)

logger = logging.getLogger(__name__)
MAX_QUESTION_LENGTH = 2000
SESSION_TITLE_LENGTH = 80
# "Hôm nay" and "tuần này" are read in Vietnam's time, whatever the server's clock zone.
BUSINESS_TIMEZONE = timezone(timedelta(hours=7))


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _session_title(question: str) -> str:
    """A new conversation is named after its first question, cut at a word boundary."""
    title = " ".join(question.split())
    if len(title) <= SESSION_TITLE_LENGTH:
        return title
    return title[:SESSION_TITLE_LENGTH].rsplit(" ", 1)[0] + "…"


def _session_history(session_id: int, excluded_question_id: int | None) -> list[dict[str, str]]:
    """The conversation's last answered turns, which the agent uses to rewrite a follow-up question.

    A question answered again after the user confirmed definitions leaves out its first answer.
    """
    answered = (
        db.session.query(AgentQuestion.question, AgentQuestion.answer)
        .filter(AgentQuestion.session_id == session_id, AgentQuestion.answer.isnot(None), AgentQuestion.error.is_(None))
        .filter(AgentQuestion.id != (excluded_question_id or 0))
        .order_by(AgentQuestion.id.desc())
        .limit(MAX_HISTORY_TURNS)
        .all()
    )
    return recent_history([
        message
        for question, answer in reversed(answered)
        for message in ({"role": "user", "content": question}, {"role": "assistant", "content": answer})
    ])


def _user_definitions(user_id: int, dashboard_id: int) -> list[dict]:
    """What the user confirmed concepts mean on this dashboard, in the shape the agent reads."""
    return [
        {
            "id": item.id, "kind": item.kind, "name": item.name, "concept": item.concept,
            "definition": item.definition, "conditions": item.conditions,
        }
        for item in user_definitions(user_id, dashboard_id)
    ]


def _record_tool_call(tool_calls: list[dict], name: str, data: dict) -> None:
    """Keep each step as the browser shows it: the start's arguments merged with the end's status and result."""
    if name == "tool_start":
        tool_calls.append({**data, "status": "running"})
    elif name == "tool_end":
        for tool_call in tool_calls:
            if tool_call["id"] == data["id"]:
                tool_call.update(data)


def _save_question(
    *,
    user_id: int,
    session_id: int,
    dashboard_id: int,
    question: str,
    history_turns: int,
    outcome: AgentOutcome,
    tool_calls: list[dict],
    retry_of: int | None,
    started: float,
    error: str | None,
) -> int | None:
    """Record the question as the conversation's next turn; a failed write is logged and never breaks the answer."""
    try:
        record = AgentQuestion(
            user_id=user_id,
            session_id=session_id,
            dashboard_id=dashboard_id,
            question=question,
            rewritten_question=outcome.rewritten_question,
            history_turns=history_turns,
            glossary_terms=outcome.glossary_terms,
            metrics=outcome.metrics,
            expert_rules=outcome.expert_rules,
            missing=[] if error else outcome.missing,
            query_result=None if error else outcome.result,
            requires_expert_rule=None if error else outcome.requires_expert_rule,
            suggestions=None if error else outcome.suggestions,
            tool_calls=tool_calls,
            clarifications=None if error else outcome.clarifications or None,
            clarification_state="pending" if outcome.clarifications and not error else None,
            retry_of=retry_of,
            status="failed" if error else outcome.status,
            answer=outcome.answer or None,
            error=error,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        db.session.add(record)
        db.session.query(AgentChatSession).filter(AgentChatSession.id == session_id).update(
            {AgentChatSession.updated_on: datetime.now(timezone.utc)}
        )
        db.session.commit()
        return record.id
    except Exception:
        db.session.rollback()
        logger.exception("Could not record the AI Agent question")
        return None


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
    def stream_chat(self):
        """Answer one question in a conversation; without `session_id` it starts one about `dashboard_id`.

        With `retry_of`, the conversation's earlier question is answered again, after the user confirmed definitions.
        The reply streams as SSE: `session` first, then each step as a tool call, the answer, and `done`, which carries
        the definitions the user is asked to confirm.
        """
        from flask_wtf.csrf import validate_csrf
        from wtforms import ValidationError

        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return self.response(403, message="CSRF token không hợp lệ.")

        body = request.get_json(silent=True) or {}
        user_id = int(current_user.id)
        ensure_question_tables(db.engine)
        session_id = body.get("session_id")
        retry_of = body.get("retry_of")
        if retry_of is not None:
            if not isinstance(retry_of, int) or isinstance(retry_of, bool) or session_id is None:
                return self.response_400(message="Câu hỏi cần trả lời lại không hợp lệ.")
            earlier = db.session.query(AgentQuestion).filter_by(id=retry_of, session_id=session_id).one_or_none()
            if earlier is None:
                return self.response_404()
            body = {**body, "question": earlier.question}
        question = body.get("question")
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_LENGTH:
            return self.response_400(message="Câu hỏi phải là chuỗi không rỗng, tối đa 2000 ký tự.")
        question = question.strip()

        if session_id is None:
            # Every conversation is about a dashboard the user may open; the answers and the log are tied to it.
            dashboard_id = body.get("dashboard_id")
            if not isinstance(dashboard_id, int) or isinstance(dashboard_id, bool):
                return self.response_400(message="Chọn dashboard trước khi hỏi AI Agent.")
        else:
            if not isinstance(session_id, int) or isinstance(session_id, bool):
                return self.response_400(message="Cuộc trò chuyện không hợp lệ.")
            chat_session = db.session.query(AgentChatSession).filter_by(id=session_id, user_id=user_id).one_or_none()
            if chat_session is None:
                return self.response_404()
            dashboard_id = chat_session.dashboard_id
        try:
            DashboardDAO.get_by_id_or_slug(dashboard_id)
        except (DashboardNotFoundError, DashboardAccessDeniedError):
            return self.response(403, message="Dashboard không tồn tại hoặc bạn không có quyền xem.")

        if session_id is None:
            chat_session = AgentChatSession(user_id=user_id, dashboard_id=dashboard_id, title=_session_title(question))
            db.session.add(chat_session)
            db.session.commit()
        session_payload = {"id": chat_session.id, "title": chat_session.title, "dashboard_id": dashboard_id}
        session_id = chat_session.id
        history = _session_history(session_id, retry_of)
        user_definitions = _user_definitions(user_id, dashboard_id)
        # The Semantic Layer is read and its metrics run as this user, so forward their session and CSRF token.
        cookie_header = request.headers.get("Cookie", "")
        csrf_token = request.headers.get("X-CSRFToken", "")

        @stream_with_context
        def events():
            started = time.monotonic()
            outcome = AgentOutcome()
            tool_calls: list[dict] = []
            error = None
            yield _event("session", session_payload)
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
            try:
                while True:
                    try:
                        name, data = next(pipeline)
                    except StopIteration as finished:
                        outcome = finished.value
                        break
                    _record_tool_call(tool_calls, name, data)
                    yield _event(name, data)
            except SemanticSourceError as ex:
                error = str(ex)
                yield _event("error", {"message": error})
            except Exception as ex:
                logger.exception("AI Agent stream failed")
                error = str(ex) or type(ex).__name__
                yield _event("error", {"message": "AI Agent không hoàn tất được câu trả lời."})
            question_id = _save_question(
                user_id=user_id, session_id=session_id, dashboard_id=dashboard_id, question=question,
                history_turns=len(history) // 2, outcome=outcome, tool_calls=tool_calls, retry_of=retry_of,
                started=started, error=error,
            )
            yield _event("done", {
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
