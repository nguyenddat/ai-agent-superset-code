from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ....core.database import handle_errors, rollback_on_error
from ....core.security import csrf_protected, require_admin
from ....migrations import ensure_agent_tables
from ..services.handling import parse_handling, parse_review_filters
from ..services.review import questions_for_review, record_handling


@api(
    id="text_to_bi_question_api",
    name="Superset AI Agent question review API",
    description="Lists the questions AI Agent could not fully resolve and records how administrators handled them.",
    resource_name="questions",
)
class AgentQuestionReviewAPI(RestApi):
    openapi_spec_tag = "Superset AI Agent"
    class_permission_name = "text_to_bi_chat_api"

    @expose("/review", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_review(self):
        """The `needs_review` questions, newest first, with their handling.

        `?handling=` narrows to one handling status and `?missing=metric` to the questions missing that kind.
        """
        require_admin()
        handling_filter, missing_filter = parse_review_filters(
            request.args.get("handling", "all"), request.args.get("missing"),
        )
        ensure_agent_tables()
        return self.response(200, **questions_for_review(handling_filter, missing_filter))

    @expose("/<int:question_id>/handling", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def set_handling(self, question_id: int):
        """Record how a question was handled; `pending` removes the decision."""
        require_admin()
        status, note = parse_handling(request.get_json(silent=True))
        ensure_agent_tables()
        question = record_handling(question_id, status, note, int(current_user.id))
        db.session.commit()
        return self.response(200, question=question)
