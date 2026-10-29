from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ....core.database import handle_errors
from ....core.security import csrf_protected, is_admin
from ...semantic_layer.services.data_model import cached_schema_graph
from ..exceptions import AnalysisLabAdminRequiredError, DatabaseIdRequiredError
from ..services.analysis import analyze, graph_view
from ..services.graph import SchemaGraph


def _require_lab_access() -> None:
    if not is_admin():
        raise AnalysisLabAdminRequiredError()


def _schema_graph(database_id: int) -> SchemaGraph:
    """The signed-in user's schema graph; raises SemanticLayerUnavailableError when the Semantic Layer cannot."""
    payload = cached_schema_graph(int(current_user.id), database_id, request.headers.get("Cookie", ""))
    return SchemaGraph.from_payload(payload)


@api(
    id="text_to_bi_schema_link_api",
    name="Superset AI Agent schema link API",
    description="Join paths and SQL over base tables, for the administrator's analysis lab.",
    resource_name="schema-link",
)
class AgentSchemaLinkAPI(RestApi):
    openapi_spec_tag = "Superset AI Agent"
    class_permission_name = "text_to_bi_chat_api"

    @expose("/access", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def access(self):
        return self.response(200, can_use_lab=is_admin())

    @expose("/graph", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def graph(self):
        """The schema graph the lab draws before any analysis."""
        _require_lab_access()
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            raise DatabaseIdRequiredError()
        return self.response(200, **graph_view(_schema_graph(database_id)))

    @expose("/analyze", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @handle_errors
    def analyze_goal(self):
        """The four-stage trace of a goal written by hand: goal, nodes, graph, chosen path, and the SQL."""
        _require_lab_access()
        body = request.get_json(silent=True) or {}
        database_id = body.get("database_id")
        if not isinstance(database_id, int) or isinstance(database_id, bool):
            raise DatabaseIdRequiredError()
        return self.response(200, **analyze(body.get("goal") or {}, _schema_graph(database_id)))
