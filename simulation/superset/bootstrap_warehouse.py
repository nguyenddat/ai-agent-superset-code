from __future__ import annotations

import json
import logging
import os

from sqlalchemy import create_engine, inspect

from superset.app import create_app


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def warehouse_uri() -> str:
    user = os.getenv("WAREHOUSE_DB_USER", "bi")
    password = os.getenv("WAREHOUSE_DB_PASSWORD", "bi_dev_password")
    host = os.getenv("WAREHOUSE_DB_HOST", "warehouse-db")
    port = os.getenv("WAREHOUSE_DB_PORT", "5432")
    database = os.getenv("WAREHOUSE_DB_NAME", "data_wh")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"


def bootstrap() -> None:
    app = create_app()
    with app.app_context():
        from superset import db
        from superset.connectors.sqla.models import SqlaTable
        from superset.models.core import Database

        database_name = os.getenv("WAREHOUSE_SUPERSET_NAME", "Weather Warehouse")
        uri = warehouse_uri()
        database = (
            db.session.query(Database)
            .filter(Database.database_name == database_name)
            .one_or_none()
        )
        if database is None:
            database = Database(database_name=database_name)
            db.session.add(database)

        database.sqlalchemy_uri = uri
        database.expose_in_sqllab = True
        database.allow_ctas = False
        database.allow_cvas = False
        database.allow_run_async = False
        db.session.commit()

        engine = create_engine(uri)
        try:
            table_names = sorted(inspect(engine).get_table_names(schema="public"))
        finally:
            engine.dispose()

        created = 0
        managed_marker = json.dumps({"managed_by": "warehouse_bootstrap"})
        for table_name in table_names:
            dataset = (
                db.session.query(SqlaTable)
                .filter(
                    SqlaTable.database_id == database.id,
                    SqlaTable.table_name == table_name,
                    SqlaTable.schema == "public",
                )
                .one_or_none()
            )
            if dataset is None:
                db.session.add(
                    SqlaTable(
                        table_name=table_name,
                        schema="public",
                        database=database,
                        extra=managed_marker,
                    )
                )
                created += 1

        legacy_dashboard_tables = {"tb_chi_tiet_thoi_tiet", "tb_tong_hop_thoi_tiet"}
        stale = (
            db.session.query(SqlaTable)
            .filter(
                SqlaTable.database_id == database.id,
                SqlaTable.schema == "public",
                SqlaTable.table_name.in_(legacy_dashboard_tables),
            )
            .all()
        )
        for dataset in stale:
            db.session.delete(dataset)
        db.session.commit()

        # Sync physical columns so extensions and metrics can see each dataset's fields.
        datasets = (
            db.session.query(SqlaTable)
            .filter(SqlaTable.database_id == database.id, SqlaTable.schema == "public")
            .all()
        )
        for dataset in datasets:
            dataset.fetch_metadata()
        db.session.commit()

        LOGGER.info(
            "Warehouse connection ready: %s; tables discovered: %s; datasets created: %s; datasets synced: %s",
            database_name,
            len(table_names),
            created,
            len(datasets),
        )


if __name__ == "__main__":
    bootstrap()
