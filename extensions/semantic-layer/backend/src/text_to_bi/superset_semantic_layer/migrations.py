import logging
import threading
import time

from sqlalchemy import inspect, text
from superset import db

from .modules.agent_ladder.models import DatasetProposal
from .modules.business_model.models import (
    BusinessCanvas,
    BusinessDomain,
    DataLayer,
    LineageCanvas,
    LineageEdge,
    business_domain_dataset,
)
from .modules.data_dictionary.models import ColumnDictionary, DatasetDictionary, DatasetGrain
from .modules.data_dictionary.services.column_semantics import default_semantic_role
from .modules.expert_rules.models import ExpertRule, ExpertRuleAuditEvent, ExpertRuleLink, ExpertRuleRevision
from .modules.glossary.models import GlossaryTerm, GlossaryTermAuditEvent, GlossaryTermLink, GlossaryTermRevision
from .modules.semantic_query.models import MetricContract, MetricContractEvent, MetricDefinition, RelationshipContract

logger = logging.getLogger(__name__)


# Arbitrary key shared by every Superset worker so only one of them migrates the dictionary tables at a time.
DICTIONARY_MIGRATION_LOCK_KEY = 74_116_201
_dictionary_tables_ready = False
_dictionary_migration_failed_at: float | None = None
DICTIONARY_MIGRATION_RETRY_SECONDS = 30
_dictionary_tables_lock = threading.Lock()


def ensure_dictionary_tables():
    """Run the dictionary table migration once per process.

    The migration takes ACCESS EXCLUSIVE locks, so concurrent dictionary requests must not run it in parallel.
    """
    global _dictionary_tables_ready, _dictionary_migration_failed_at
    if _dictionary_tables_ready:
        return
    with _dictionary_tables_lock:
        if _dictionary_tables_ready:
            return
        # A failing migration holds ACCESS EXCLUSIVE locks while it runs, so requests must not retry it back to back.
        failed_at = _dictionary_migration_failed_at
        if failed_at is not None and time.monotonic() - failed_at < DICTIONARY_MIGRATION_RETRY_SECONDS:
            raise RuntimeError("The dictionary table migration failed recently; see the earlier error in the log.")
        try:
            if db.engine.dialect.name != "postgresql":
                _migrate_dictionary_tables()
            else:
                with db.engine.connect() as lock_connection:
                    lock_connection.execute(
                        text("SELECT pg_advisory_lock(:key)"), {"key": DICTIONARY_MIGRATION_LOCK_KEY}
                    )
                    try:
                        _migrate_dictionary_tables()
                    finally:
                        lock_connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": DICTIONARY_MIGRATION_LOCK_KEY}
                        )
        except Exception:
            _dictionary_migration_failed_at = time.monotonic()
            logger.exception("Dictionary migration failed; next attempt in %ss", DICTIONARY_MIGRATION_RETRY_SECONDS)
            raise
        _dictionary_migration_failed_at = None
        _dictionary_tables_ready = True


def _migrate_dictionary_tables():
    """Create extension tables and upgrade the earlier column dictionary schema.

    Creating tables, adding columns and seeding are portable. Upgrading installs that predate the current column
    dictionary schema renames and alters constraints, which only PostgreSQL installations ever needed.
    """
    postgres = db.engine.dialect.name == "postgresql"
    inspector = inspect(db.engine)
    if postgres and inspector.has_table(ColumnDictionary.__tablename__):
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

    # Layers come first: dataset dictionaries reference them.
    DataLayer.__table__.create(bind=db.engine, checkfirst=True)
    DatasetDictionary.__table__.create(bind=db.engine, checkfirst=True)
    ColumnDictionary.__table__.create(bind=db.engine, checkfirst=True)
    DatasetGrain.__table__.create(bind=db.engine, checkfirst=True)
    BusinessDomain.__table__.create(bind=db.engine, checkfirst=True)
    business_domain_dataset.create(bind=db.engine, checkfirst=True)
    LineageEdge.__table__.create(bind=db.engine, checkfirst=True)
    BusinessCanvas.__table__.create(bind=db.engine, checkfirst=True)
    LineageCanvas.__table__.create(bind=db.engine, checkfirst=True)
    MetricContract.__table__.create(bind=db.engine, checkfirst=True)
    MetricContractEvent.__table__.create(bind=db.engine, checkfirst=True)
    MetricDefinition.__table__.create(bind=db.engine, checkfirst=True)
    RelationshipContract.__table__.create(bind=db.engine, checkfirst=True)
    # Glossary parent tables must exist before immutable revisions, links, and audit evidence.
    GlossaryTerm.__table__.create(bind=db.engine, checkfirst=True)
    GlossaryTermRevision.__table__.create(bind=db.engine, checkfirst=True)
    GlossaryTermLink.__table__.create(bind=db.engine, checkfirst=True)
    GlossaryTermAuditEvent.__table__.create(bind=db.engine, checkfirst=True)
    # Expert rule routes never issue DDL, so this migration is their only table bootstrap.
    ExpertRule.__table__.create(bind=db.engine, checkfirst=True)
    ExpertRuleRevision.__table__.create(bind=db.engine, checkfirst=True)
    ExpertRuleLink.__table__.create(bind=db.engine, checkfirst=True)
    ExpertRuleAuditEvent.__table__.create(bind=db.engine, checkfirst=True)
    DatasetProposal.__table__.create(bind=db.engine, checkfirst=True)

    with db.engine.begin() as connection:
        contract_columns = {column["name"] for column in inspect(connection).get_columns(MetricContract.__tablename__)}
        if "revoker_id" not in contract_columns:
            revoker_column = "INTEGER REFERENCES ab_user (id) ON DELETE SET NULL" if postgres else "INTEGER"
            connection.execute(text(f"ALTER TABLE text_to_bi_metric_contract ADD COLUMN revoker_id {revoker_column}"))
        if "revoked_at" not in contract_columns:
            connection.execute(
                text("ALTER TABLE text_to_bi_metric_contract ADD COLUMN revoked_at TIMESTAMP WITH TIME ZONE")
            )
        if "origin" not in contract_columns:
            connection.execute(
                text("ALTER TABLE text_to_bi_metric_contract ADD COLUMN origin VARCHAR(16) NOT NULL DEFAULT 'manual'")
            )
        if postgres:
            contract_constraints = inspect(connection).get_foreign_keys(MetricContract.__tablename__)
            has_revoker_fk = any(
                constraint.get("constrained_columns") == ["revoker_id"]
                and constraint.get("referred_table") == "ab_user"
                and constraint.get("referred_columns") == ["id"]
                for constraint in contract_constraints
            )
            if not has_revoker_fk:
                connection.execute(
                    text(
                        "ALTER TABLE text_to_bi_metric_contract "
                        "ADD CONSTRAINT fk_text_to_bi_metric_contract_revoker "
                        "FOREIGN KEY (revoker_id) REFERENCES ab_user (id) ON DELETE SET NULL"
                    )
                )
        contract_indexes = {index["name"] for index in inspect(connection).get_indexes(MetricContract.__tablename__)}
        if "ix_text_to_bi_metric_contract_revoker_id" not in contract_indexes:
            connection.execute(
                text("CREATE INDEX ix_text_to_bi_metric_contract_revoker_id ON text_to_bi_metric_contract (revoker_id)")
            )

    with db.engine.begin() as connection:
        relationship_columns = {
            column["name"] for column in inspect(connection).get_columns(RelationshipContract.__tablename__)
        }
        for column_name, column_type in (
            ("source", "VARCHAR(16)"),
            ("verification", "TEXT"),
            ("verified_hash", "VARCHAR(64)"),
            ("verified_at", "TIMESTAMP WITH TIME ZONE"),
        ):
            if column_name not in relationship_columns:
                connection.execute(
                    text(f"ALTER TABLE text_to_bi_relationship_contract ADD COLUMN {column_name} {column_type}")
                )

    with db.engine.begin() as connection:
        layer_columns = {column["name"] for column in inspect(connection).get_columns(DataLayer.__tablename__)}
        # Layers created before levels existed flowed one after another, so each keeps a level of its own.
        if "level" not in layer_columns:
            connection.execute(text("ALTER TABLE text_to_bi_data_layer ADD COLUMN level INTEGER NOT NULL DEFAULT 0"))
            layer_ids = connection.execute(
                text("SELECT id FROM text_to_bi_data_layer ORDER BY sort_order, id")
            ).scalars()
            for position, layer_id in enumerate(list(layer_ids)):
                connection.execute(
                    text("UPDATE text_to_bi_data_layer SET level = :level WHERE id = :id"),
                    {"level": position, "id": layer_id},
                )

    with db.engine.begin() as connection:
        edge_columns = {column["name"] for column in inspect(connection).get_columns(LineageEdge.__tablename__)}
        # Rows created before is_manual existed were all manual edges or hidden overrides.
        for column_name, column_type in (("is_manual", "BOOLEAN NOT NULL DEFAULT TRUE"), ("color", "VARCHAR(16)")):
            if column_name not in edge_columns:
                connection.execute(text(f"ALTER TABLE text_to_bi_lineage_edge ADD COLUMN {column_name} {column_type}"))

    with db.engine.begin() as connection:
        dataset_columns = {
            column["name"] for column in inspect(connection).get_columns(DatasetDictionary.__tablename__)
        }
        dataset_columns_to_add = (
            ("description", "TEXT"),
            ("grain", "TEXT"),
            ("create_column", "VARCHAR(255)"),
            ("dataset_type", "VARCHAR(32)"),
            ("layer_id", "INTEGER REFERENCES text_to_bi_data_layer (id) ON DELETE SET NULL"),
            ("time_column", "VARCHAR(255)"),
            ("row_kind_column", "VARCHAR(255)"),
            ("indicator_model", "TEXT"),
        )
        for column_name, column_type in dataset_columns_to_add:
            if column_name not in dataset_columns:
                connection.execute(
                    text(f"ALTER TABLE text_to_bi_dataset_dictionary ADD COLUMN {column_name} {column_type}")
                )

    with db.engine.begin() as connection:
        dictionary_columns = {
            column["name"] for column in inspect(connection).get_columns(ColumnDictionary.__tablename__)
        }
        if "temporal_kind" not in dictionary_columns:
            connection.execute(text("ALTER TABLE text_to_bi_column_dictionary ADD COLUMN temporal_kind VARCHAR(16)"))
            # Rows seeded before temporal kinds existed take theirs from the type recorded when they were seeded.
            connection.execute(
                text(
                    "UPDATE text_to_bi_column_dictionary SET temporal_kind = 'timestamp' "
                    "WHERE UPPER(data_type) LIKE '%TIMESTAMP%' OR UPPER(data_type) LIKE '%DATETIME%'"
                )
            )
            connection.execute(
                text(
                    "UPDATE text_to_bi_column_dictionary SET temporal_kind = 'date' "
                    "WHERE UPPER(TRIM(data_type)) = 'DATE'"
                )
            )

    with db.engine.begin() as connection:
        dictionary_columns = {
            column["name"] for column in inspect(connection).get_columns(ColumnDictionary.__tablename__)
        }
        added = False
        for column_name, column_type in (
            ("semantic_role", "VARCHAR(16)"),
            ("aggregations", "TEXT"),
            ("synonyms", "TEXT"),
            ("description", "TEXT"),
        ):
            if column_name not in dictionary_columns:
                connection.execute(
                    text(f"ALTER TABLE text_to_bi_column_dictionary ADD COLUMN {column_name} {column_type}")
                )
                added = True
        if added:
            # Rows seeded before roles existed take the role default_semantic_role gives them.
            unset = connection.execute(
                text(
                    "SELECT entry.id, entry.data_type, entry.temporal_kind, entry.is_pk OR entry.is_fk AS is_key, "
                    "entry.column_name = dataset.row_kind_column AS is_row_kind "
                    "FROM text_to_bi_column_dictionary entry "
                    "LEFT JOIN text_to_bi_dataset_dictionary dataset ON dataset.id = entry.dataset_id "
                    "WHERE entry.semantic_role IS NULL"
                )
            ).all()
            if unset:
                connection.execute(
                    text("UPDATE text_to_bi_column_dictionary SET semantic_role = :role WHERE id = :id"),
                    [
                        {
                            "id": row.id,
                            "role": default_semantic_role(
                                row.data_type,
                                row.temporal_kind,
                                bool(row.is_key),
                                bool(row.is_row_kind),
                            ),
                        }
                        for row in unset
                    ],
                )

    if postgres:
        with db.engine.begin() as connection:
            columns = {
                column["name"]: column for column in inspect(connection).get_columns(ColumnDictionary.__tablename__)
            }
            if "column_name" not in columns:
                connection.execute(text("ALTER TABLE text_to_bi_column_dictionary ADD COLUMN column_name VARCHAR(255)"))
            if "column_name" not in columns or columns["column_name"]["nullable"]:
                connection.execute(
                    text("UPDATE text_to_bi_column_dictionary SET column_name = display_name WHERE column_name IS NULL")
                )
                connection.execute(
                    text("ALTER TABLE text_to_bi_column_dictionary ALTER COLUMN column_name SET NOT NULL")
                )

            unique_constraints = inspect(connection).get_unique_constraints(ColumnDictionary.__tablename__)
            has_column_name_constraint = any(
                constraint.get("column_names") == ["dataset_id", "column_name"] for constraint in unique_constraints
            )
            preparer = connection.dialect.identifier_preparer
            for constraint in unique_constraints:
                if constraint.get("column_names") == ["dataset_id", "display_name"] and constraint.get("name"):
                    connection.execute(
                        text(
                            "ALTER TABLE text_to_bi_column_dictionary DROP CONSTRAINT "
                            f"{preparer.quote(constraint['name'])}"
                        )
                    )
            if not has_column_name_constraint:
                connection.execute(
                    text(
                        "ALTER TABLE text_to_bi_column_dictionary "
                        "ADD CONSTRAINT uq_text_to_bi_column_dataset_column_name "
                        "UNIQUE (dataset_id, column_name)"
                    )
                )

    with db.engine.begin() as connection:
        # Seed a basic dictionary record for every existing Superset dataset.
        connection.execute(
            text(
                "INSERT INTO text_to_bi_dataset_dictionary "
                "(id, dataset_name, display_name, description) "
                "SELECT id, table_name, table_name, description "
                "FROM tables WHERE id NOT IN (SELECT id FROM text_to_bi_dataset_dictionary)"
            )
        )

        if postgres:
            constraints = inspect(connection).get_foreign_keys(ColumnDictionary.__tablename__)
            dataset_constraints = [
                constraint for constraint in constraints if constraint.get("constrained_columns") == ["dataset_id"]
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
                        text(f"ALTER TABLE text_to_bi_column_dictionary DROP CONSTRAINT {constraint_name}")
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
                    text(f"ALTER INDEX {old_index_name} RENAME TO ix_text_to_bi_column_dictionary_dataset_id")
                )
