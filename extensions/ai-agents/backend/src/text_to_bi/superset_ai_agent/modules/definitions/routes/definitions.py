from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ....core.database import handle_errors, rollback_on_error
from ....core.security import csrf_protected, require_admin
from ....migrations import ensure_agent_tables
from ..dependencies import user_definition_repository
from ..exceptions import DashboardIdRequiredError
from ..services.definitions import (
    definitions_for_review,
    definitions_on_dashboard,
    require_own_definition,
    serialize_definition,
    set_review_status,
    update_definition,
)
from ..services.parsing import parse_review


@api(
    id="text_to_bi_user_definition_api",
    name="Superset AI Agent user definitions API",
    description="The signed-in user's own definitions of business concepts, and their review by administrators.",
    resource_name="definitions",
)
class AgentUserDefinitionAPI(RestApi):
    openapi_spec_tag = "Superset AI Agent"
    class_permission_name = "text_to_bi_chat_api"

    @expose("/", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_own(self):
        """The user's definitions on `?dashboard_id=`, shared by all their conversations about that dashboard."""
        dashboard_id = request.args.get("dashboard_id", type=int)
        if dashboard_id is None:
            raise DashboardIdRequiredError()
        ensure_agent_tables()
        definitions = definitions_on_dashboard(int(current_user.id), dashboard_id)
        return self.response(200, result=[serialize_definition(item) for item in definitions])

    @expose("/<int:definition_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_own(self, definition_id: int):
        """Change what the user's definition says; administrators see it again as not yet reviewed."""
        ensure_agent_tables()
        definition = require_own_definition(definition_id, int(current_user.id))
        update_definition(definition, request.get_json(silent=True), request.headers.get("Cookie", ""))
        db.session.commit()
        return self.response(200, result=serialize_definition(definition))

    @expose("/<int:definition_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_own(self, definition_id: int):
        """Forget the user's definition; the agent asks about the concept again."""
        ensure_agent_tables()
        user_definition_repository().delete(require_own_definition(definition_id, int(current_user.id)))
        db.session.commit()
        return self.response(200, message="Đã xoá định nghĩa.")

    @expose("/review", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_review(self):
        """Every user's definitions, most recently changed first (admin only)."""
        require_admin()
        ensure_agent_tables()
        return self.response(200, definitions=definitions_for_review())

    @expose("/review", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def set_review(self):
        """Record `{ids, status}`: a shared term or rule now covers the concept, it stays personal, or is reopened."""
        require_admin()
        definition_ids, status = parse_review(request.get_json(silent=True))
        ensure_agent_tables()
        updated = set_review_status(definition_ids, status, int(current_user.id))
        db.session.commit()
        return self.response(200, updated=updated)
