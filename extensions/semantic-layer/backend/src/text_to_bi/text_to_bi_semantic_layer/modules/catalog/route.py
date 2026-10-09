import json

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset.connectors.sqla.models import SqlaTable
from superset.models.dashboard import Dashboard
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api


SEMANTIC_LAYER_DATASET_IDS_KEY = "text_to_bi_semantic_layer_dataset_ids"


@api(
    id="text_to_bi_semantic_layer_api",
    name="Text to BI Semantic Layer API",
    description="Admin access check for the Semantic Layer dashboard extension.",
    resource_name="semantic-layer",
)
class SemanticLayerAPI(RestApi):
    openapi_spec_tag = "Text to BI Semantic Layer"
    class_permission_name = "text_to_bi_semantic_layer_api"

    @staticmethod
    def _is_admin():
        return any(role.name == "Admin" for role in current_user.roles)

    @expose("/access", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_access(self):
        """Return whether the authenticated user is a Superset administrator."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        return self.response(200, is_admin=True)

    @expose("/dashboard/<int:dashboard_id>/datasets", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_dashboard_datasets(self, dashboard_id: int):
        """Return datasets explicitly attached to a dashboard's semantic layer."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        dashboard = db.session.get(Dashboard, dashboard_id)
        if dashboard is None:
            return self.response(404, message="Dashboard not found.")
        try:
            metadata = json.loads(dashboard.json_metadata or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        dataset_ids = metadata.get(SEMANTIC_LAYER_DATASET_IDS_KEY, [])
        dataset_ids = sorted({int(value) for value in dataset_ids if str(value).isdigit()})
        return self.response(200, dataset_ids=dataset_ids)

    @expose("/dashboard/<int:dashboard_id>/datasets", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    def add_dashboard_dataset(self, dashboard_id: int):
        """Attach an existing dataset to a dashboard's semantic layer."""
        if not self._is_admin():
            return self.response(403, message="Admin access required.")
        dashboard = db.session.get(Dashboard, dashboard_id)
        if dashboard is None:
            return self.response(404, message="Dashboard not found.")
        payload = request.get_json(silent=True) or {}
        try:
            dataset_id = int(payload.get("dataset_id"))
        except (TypeError, ValueError):
            return self.response_400(message="dataset_id must be an integer.")
        if dataset_id <= 0:
            return self.response_400(message="dataset_id must be a positive integer.")
        if db.session.get(SqlaTable, dataset_id) is None:
            return self.response(404, message="Dataset not found.")
        try:
            metadata = json.loads(dashboard.json_metadata or "{}")
            dataset_ids = metadata.get(SEMANTIC_LAYER_DATASET_IDS_KEY, [])
            existing_ids = {int(value) for value in dataset_ids if str(value).isdigit()}
            existing_ids.add(dataset_id)
            metadata[SEMANTIC_LAYER_DATASET_IDS_KEY] = sorted(existing_ids)
            dashboard.json_metadata = json.dumps(metadata)
            db.session.commit()
            return self.response(200, dataset_ids=metadata[SEMANTIC_LAYER_DATASET_IDS_KEY])
        except Exception as ex:  # noqa: BLE001
            db.session.rollback()
            return self.response_500(message=str(ex))
