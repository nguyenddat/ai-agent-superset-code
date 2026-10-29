from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ..access import is_admin, valid_csrf
from ..chat.semantic_source import SemanticSourceError, cached_schema_graph
from .analysis import analyze, graph_view
from .graph import SchemaGraph

ADMIN_ONLY = "Chỉ quản trị viên dùng được phòng thử phân tích."


@api(
    id="text_to_bi_schema_link_api",
    name="Superset AI Agent schema link API",
    description="Join paths and SQL over base tables, for the administrator's analysis lab.",
    resource_name="schema-link",
)
class AgentSchemaLinkAPI(RestApi):
    openapi_spec_tag = "Superset AI Agent"
    class_permission_name = "text_to_bi_chat_api"

    @staticmethod
    def _schema_graph(database_id: int) -> SchemaGraph:
        """The signed-in user's schema graph; raises `SemanticSourceError` when the Semantic Layer cannot give it."""
        payload = cached_schema_graph(int(current_user.id), database_id, request.headers.get("Cookie", ""))
        return SchemaGraph.from_payload(payload)

    @expose("/access", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def access(self):
        return self.response(200, can_use_lab=is_admin())

    @expose("/graph", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def graph(self):
        """The schema graph the lab draws before any analysis."""
        if not is_admin():
            return self.response(403, message=ADMIN_ONLY)
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            return self.response_400(message="Cần database_id.")
        try:
            schema_graph = self._schema_graph(database_id)
        except SemanticSourceError as ex:
            return self.response(502, message=str(ex))
        return self.response(200, **graph_view(schema_graph))

    @expose("/analyze", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    def analyze_goal(self):
        """The four-stage trace of a goal written by hand: goal, nodes, graph, chosen path, and the SQL."""
        if not is_admin():
            return self.response(403, message=ADMIN_ONLY)
        if not valid_csrf():
            return self.response(403, message="CSRF token không hợp lệ.")
        body = request.get_json(silent=True) or {}
        database_id = body.get("database_id")
        if not isinstance(database_id, int) or isinstance(database_id, bool):
            return self.response_400(message="Cần database_id.")
        try:
            schema_graph = self._schema_graph(database_id)
        except SemanticSourceError as ex:
            return self.response(502, message=str(ex))
        return self.response(200, **analyze(body.get("goal") or {}, schema_graph))
