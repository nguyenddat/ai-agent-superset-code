"""Schema link endpoints: the admin analysis lab, run on the schema graph read as the signed-in user.

Until linking from a question exists, an administrator writes the goal by hand and sees how it becomes a join tree and
SQL. The graph comes from the Semantic Layer's `/schema-graph` with the user's session cookie, so it holds only the
base tables they may read in full; nothing here runs the SQL it builds.
"""

import threading
import time

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ..chat.semantic_source import CATALOG_CACHE_SECONDS, SEMANTIC_LAYER_API, SemanticSourceError, _get_json
from .analysis import analyze
from .graph import SchemaGraph

_cache_lock = threading.Lock()
_cached_graphs: dict[tuple[int, int], tuple[float, dict]] = {}


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


def cached_schema_graph(user_id: int, database_id: int, cookie_header: str) -> dict:
    """The user's schema graph of one database, read again after `CATALOG_CACHE_SECONDS`; per user, as access is."""
    now = time.monotonic()
    key = (user_id, database_id)
    with _cache_lock:
        cached = _cached_graphs.get(key)
    if cached and now - cached[0] < CATALOG_CACHE_SECONDS:
        return cached[1]
    payload = _get_json(f"{SEMANTIC_LAYER_API}/schema-graph?database_id={database_id}", cookie_header)
    with _cache_lock:
        _cached_graphs[key] = (now, payload)
    return payload


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
    def access(self):
        return self.response(200, can_use_lab=_is_admin())

    @expose("/graph", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def graph(self):
        """The schema graph the lab draws before any analysis."""
        if not _is_admin():
            return self.response(403, message="Chỉ quản trị viên dùng được phòng thử phân tích.")
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            return self.response_400(message="Cần database_id.")
        try:
            payload = cached_schema_graph(int(current_user.id), database_id, request.headers.get("Cookie", ""))
        except SemanticSourceError as ex:
            return self.response(502, message=str(ex))
        return self.response(200, **payload)

    @expose("/analyze", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    def analyze_goal(self):
        """The four-stage trace of a goal written by hand: goal, nodes, graph, chosen path, and the SQL."""
        if not _is_admin():
            return self.response(403, message="Chỉ quản trị viên dùng được phòng thử phân tích.")
        if not _valid_csrf():
            return self.response(403, message="CSRF token không hợp lệ.")
        body = request.get_json(silent=True) or {}
        database_id = body.get("database_id")
        if not isinstance(database_id, int) or isinstance(database_id, bool):
            return self.response_400(message="Cần database_id.")
        try:
            payload = cached_schema_graph(int(current_user.id), database_id, request.headers.get("Cookie", ""))
        except SemanticSourceError as ex:
            return self.response(502, message=str(ex))
        return self.response(200, **analyze(body.get("goal") or {}, SchemaGraph.from_payload(payload)))
