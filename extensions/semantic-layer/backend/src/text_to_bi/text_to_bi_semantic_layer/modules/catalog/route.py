import json

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from sqlalchemy import inspect, text
from superset import db
from superset.connectors.sqla.models import SqlaTable
from superset.models.dashboard import Dashboard
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ...models.column_dictionary import ColumnDictionary
from ...models.dataset_dictionary import DatasetDictionary


SEMANTIC_LAYER_DATASET_IDS_KEY = "text_to_bi_semantic_layer_dataset_ids"


def _ensure_dictionary_tables():
    """Create extension tables and upgrade the earlier column dictionary schema."""
    inspector = inspect(db.engine)
    if inspector.has_table(ColumnDictionary.__tablename__):
        columns = {column["name"] for column in inspector.get_columns(ColumnDictionary.__tablename__)}
        if "table_id" in columns and "dataset_id" not in columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE text_to_bi_column_dictionary "
                        "RENAME COLUMN table_id TO dataset_id"
                    )
                )
                unique_constraints = {
                    constraint["name"]
                    for constraint in inspect(connection).get_unique_constraints(
                        ColumnDictionary.__tablename__
                    )
                }
                old_constraint = "uq_text_to_bi_column_table_display_name"
                if old_constraint in unique_constraints:
                    connection.execute(
                        text(
                            "ALTER TABLE text_to_bi_column_dictionary "
                            "RENAME CONSTRAINT uq_text_to_bi_column_table_display_name "
                            "TO uq_text_to_bi_column_dataset_display_name"
                        )
                    )

    DatasetDictionary.__table__.create(bind=db.engine, checkfirst=True)
    ColumnDictionary.__table__.create(bind=db.engine, checkfirst=True)

    with db.engine.begin() as connection:
        # Seed a basic dictionary record for every existing Superset dataset.
        connection.execute(
            text(
                "INSERT INTO text_to_bi_dataset_dictionary "
                "(id, dataset_name, display_name, description) "
                "SELECT id, table_name, table_name, description "
                "FROM tables "
                "ON CONFLICT (id) DO NOTHING"
            )
        )

        constraints = inspect(connection).get_foreign_keys(ColumnDictionary.__tablename__)
        dataset_constraints = [
            constraint
            for constraint in constraints
            if constraint.get("constrained_columns") == ["dataset_id"]
        ]
        has_dictionary_fk = any(
            constraint.get("referred_table") == DatasetDictionary.__tablename__
            and constraint.get("referred_columns") == ["id"]
            for constraint in dataset_constraints
        )
        preparer = connection.dialect.identifier_preparer
        for constraint in dataset_constraints:
            if constraint.get("referred_table") != DatasetDictionary.__tablename__:
                constraint_name = preparer.quote(constraint["name"])
                connection.execute(
                    text(
                        f"ALTER TABLE text_to_bi_column_dictionary "
                        f"DROP CONSTRAINT {constraint_name}"
                    )
                )
        if not has_dictionary_fk:
            connection.execute(
                text(
                    "ALTER TABLE text_to_bi_column_dictionary "
                    "ADD CONSTRAINT fk_text_to_bi_column_dataset_dictionary "
                    "FOREIGN KEY (dataset_id) "
                    "REFERENCES text_to_bi_dataset_dictionary (id) ON DELETE CASCADE"
                )
            )

        indexes = {index["name"] for index in inspect(connection).get_indexes(ColumnDictionary.__tablename__)}
        old_index = "ix_text_to_bi_column_dictionary_table_id"
        if old_index in indexes:
            old_index_name = preparer.quote(old_index)
            connection.execute(
                text(
                    f"ALTER INDEX {old_index_name} "
                    "RENAME TO ix_text_to_bi_column_dictionary_dataset_id"
                )
            )


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
        _ensure_dictionary_tables()
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
