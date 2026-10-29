import json
import logging
from datetime import datetime, timezone
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from sqlalchemy import text
from superset import db
from superset.connectors.sqla.models import SqlaTable

from ....common.utils.type_formatter import iso_datetime
from ....core.database import handle_errors, rollback_on_error
from ....core.security import csrf_protected, require_admin
from ....migrations import ensure_dictionary_tables
from ...agent_ladder.services.agent_ladder import BASE_DATASET
from ...data_dictionary.dependencies import column_dictionary_repository, dataset_dictionary_repository
from ...data_dictionary.models import ColumnDictionary
from ...data_dictionary.services.seeding import seed_dictionary
from ...superset.exceptions import DatasetNotFoundError
from ...superset.services.datasets import get_dataset, require_dataset
from ..dependencies import relationship_contract_repository
from ..exceptions import (
    ApprovedContractExistsError,
    ForeignKeyColumnNotFoundError,
    RelationshipCandidateRequiredError,
    RelationshipContractNotFoundError,
    RelationshipValidationError,
)
from ..models import RelationshipContract
from ..services.relationship_discovery import (
    SOURCES,
    VERIFICATION_TIMEOUT_MS,
    TableKeys,
    database_suggestions,
    merged_suggestions,
    naming_suggestions,
    stored_verification,
    types_match,
    verification_queries,
    verification_result,
)
from ..services.relationship_lookup import base_tables, relationship_ends
from ..services.relationships import (
    RelationshipEnd,
    relationship_cardinality,
    relationship_contract_hash,
    relationship_is_approved_current,
)

logger = logging.getLogger(__name__)


class RelationshipRoutes:
    """Routes of SemanticLayerAPI. Relationships between datasets: suggestions, data checks and their contracts."""

    @staticmethod
    def _fk_entry(dataset_id: int, column_id: int) -> ColumnDictionary | None:
        return column_dictionary_repository().get_in_dataset(dataset_id, column_id)

    @staticmethod
    def _relationship_contract_for(from_dataset_id: int, from_column: str) -> RelationshipContract | None:
        return relationship_contract_repository().from_column(from_dataset_id, from_column)

    @staticmethod
    def _relationship_contract_fields(contract: RelationshipContract) -> dict[str, Any]:
        """A contract's stored fields; its data check counts only while it was made on the current snapshot."""
        verified_hash = getattr(contract, "verified_hash", None)
        verified = bool(verified_hash) and verified_hash == getattr(contract, "contract_hash", None)
        verified_at = getattr(contract, "verified_at", None)
        return {
            "id": contract.id,
            "from_dataset_id": contract.from_dataset_id,
            "from_column": contract.from_column,
            "to_dataset_id": contract.to_dataset_id,
            "to_column": contract.to_column,
            "cardinality": contract.cardinality,
            "status": contract.status,
            "source": getattr(contract, "source", None),
            "owner_id": contract.owner_id,
            "approver_id": contract.approver_id,
            "approved_at": iso_datetime(contract.approved_at),
            "revoker_id": contract.revoker_id,
            "revoked_at": iso_datetime(contract.revoked_at),
            "verification": stored_verification(getattr(contract, "verification", None)) if verified else None,
            "verified_at": verified_at.isoformat() if verified and verified_at else None,
        }

    @staticmethod
    def _serialize_relationship_contract(
        contract: RelationshipContract, source: RelationshipEnd, target: RelationshipEnd
    ) -> dict[str, Any]:
        # Metric execution never joins; a current approved contract on base tables is an edge for schema link instead.
        current = relationship_is_approved_current(contract, source, target)
        return {**RelationshipRoutes._relationship_contract_fields(contract), "current": current, "executable": False}

    def _relationship_contract_context(
        self, dataset_id: int, column_id: int
    ) -> tuple[RelationshipEnd, RelationshipEnd]:
        entry = self._fk_entry(dataset_id, column_id)
        if entry is None:
            raise ForeignKeyColumnNotFoundError()
        ends = relationship_ends(entry)
        if ends is None:
            raise RelationshipValidationError("The referenced dictionary column or dataset no longer exists.")
        relationship_cardinality(*ends)
        return ends

    @expose("/dataset/<int:dataset_id>/relationships/<int:column_id>/contract/candidate", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_relationship_contract_candidate(self, dataset_id: int, column_id: int):
        """Snapshot an eligible declared FK relationship for administrator approval."""
        require_admin()
        ensure_dictionary_tables()
        source, target = self._relationship_contract_context(dataset_id, column_id)
        body = request.get_json(silent=True)
        origin = body.get("source") if isinstance(body, dict) else None
        contract = self._snapshot_relationship_candidate(source, target, origin if origin in SOURCES else None)
        if contract is None:
            raise ApprovedContractExistsError()
        db.session.commit()
        return self.response(201, contract=self._serialize_relationship_contract(contract, source, target))

    def _snapshot_relationship_candidate(
        self,
        source: RelationshipEnd,
        target: RelationshipEnd,
        origin: str | None,
    ) -> RelationshipContract | None:
        """A candidate contract snapshotting the relationship as it is now; None while an approved one is current.

        A new snapshot clears the approval, the revocation and the data check, which describe the earlier one.
        """
        cardinality = relationship_cardinality(source, target)
        contract = self._relationship_contract_for(source.dataset.id, source.entry.column_name)
        if contract is not None and relationship_is_approved_current(contract, source, target):
            return None
        # As for metric contracts, hash before a new contract joins the session so autoflush cannot insert it half-set.
        contract_hash = relationship_contract_hash(source, target, cardinality)
        if contract is None:
            contract = RelationshipContract(
                from_dataset_id=source.dataset.id, from_column=source.entry.column_name, owner_id=current_user.id
            )
        contract.to_dataset_id = target.dataset.id
        contract.to_column = target.entry.column_name
        contract.cardinality = cardinality
        contract.contract_hash = contract_hash
        relationship_contract_repository().add(contract, flush=False)
        contract.source = origin or getattr(contract, "source", None) or "dictionary"
        contract.approver_id = None
        contract.approved_at = None
        contract.revoker_id = None
        contract.revoked_at = None
        contract.verification = None
        contract.verified_hash = None
        contract.verified_at = None
        contract.status = "candidate"
        return contract

    @expose("/dataset/<int:dataset_id>/relationships/<int:column_id>/contract/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve_relationship_contract(self, dataset_id: int, column_id: int):
        require_admin()
        ensure_dictionary_tables()
        source, target = self._relationship_contract_context(dataset_id, column_id)
        contract = self._relationship_contract_for(source.dataset.id, source.entry.column_name)
        if contract is None:
            raise RelationshipContractNotFoundError()
        if contract.status != "candidate":
            raise RelationshipValidationError("Only a candidate relationship contract can be approved.")
        cardinality = relationship_cardinality(source, target)
        if contract.contract_hash != relationship_contract_hash(source, target, cardinality):
            raise RelationshipValidationError("Relationship changed; create a new candidate before approval.")
        verification = self._relationship_contract_fields(contract)["verification"]
        if not verification or not verification.get("passed"):
            raise RelationshipValidationError(
                "Check the data first: the target column must hold each value once and the types must match."
            )
        contract.status = "approved"
        contract.approver_id = current_user.id
        contract.approved_at = datetime.now(timezone.utc)
        db.session.commit()
        return self.response(200, contract=self._serialize_relationship_contract(contract, source, target))

    @expose("/dataset/<int:dataset_id>/relationships/<int:column_id>/contract/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke_relationship_contract(self, dataset_id: int, column_id: int):
        require_admin()
        ensure_dictionary_tables()
        entry = self._fk_entry(dataset_id, column_id)
        contract = self._relationship_contract_for(dataset_id, entry.column_name) if entry is not None else None
        contract_id = request.args.get("contract_id", type=int)
        if contract_id is not None:
            candidate = relationship_contract_repository().get(contract_id)
            # A contract ID is only an alternate key for this route's relationship when
            # the path FK entry independently binds it to the same source column. If the
            # entry is gone, the request no longer carries enough information to prove
            # which relationship the caller intended, even when the ID belongs to this dataset.
            if (
                candidate is None
                or entry is None
                or candidate.from_dataset_id != dataset_id
                or candidate.from_column != entry.column_name
                or (contract is not None and candidate.id != contract.id)
            ):
                raise RelationshipContractNotFoundError()
            contract = candidate
        if contract is None:
            raise RelationshipContractNotFoundError()
        contract.status = "revoked"
        contract.revoker_id = current_user.id
        contract.revoked_at = datetime.now(timezone.utc)
        db.session.commit()
        ends = relationship_ends(entry) if entry is not None else None
        if ends is None:
            return self.response(
                200,
                contract={**self._relationship_contract_fields(contract), "current": False, "executable": False},
            )
        return self.response(200, contract=self._serialize_relationship_contract(contract, *ends))

    @staticmethod
    def _table_keys(dataset: SqlaTable) -> TableKeys:
        """A physical dataset's columns and the dictionary columns that hold each value once on their own."""
        live = {
            str(column.column_name): str(getattr(column, "type", None) or "")
            for column in dataset.columns
            if getattr(column, "is_active", None) is True and not getattr(column, "expression", None)
        }
        entries = [
            row
            for row in column_dictionary_repository().list_for_dataset(dataset.id)
            if row.column_name in live
        ]
        primary = [row.column_name for row in entries if row.is_pk]
        unique = {row.column_name for row in entries if row.is_unique} | (set(primary) if len(primary) == 1 else set())
        return TableKeys(dataset.id, dataset.schema, dataset.table_name, live, frozenset(unique))

    def _relationship_row(self, entry: ColumnDictionary) -> dict[str, Any] | None:
        ends = relationship_ends(entry)
        if ends is None:
            return None
        source, target = ends
        try:
            cardinality, problem = relationship_cardinality(source, target), None
        except ValueError as ex:
            cardinality, problem = None, str(ex)
        contract = self._relationship_contract_for(source.dataset.id, entry.column_name)
        return {
            "column_id": entry.id,
            "from_dataset_id": source.dataset.id,
            "from_dataset_name": source.dataset.table_name,
            "from_column": entry.column_name,
            "to_dataset_id": target.dataset.id,
            "to_dataset_name": target.dataset.table_name,
            "to_column": target.entry.column_name,
            "cardinality": cardinality,
            "problem": problem,
            "contract": self._serialize_relationship_contract(contract, source, target) if contract else None,
        }

    @expose("/dataset/<int:dataset_id>/relationships", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_relationships(self, dataset_id: int):
        """The dataset's declared relationships, going out and coming in, with their contracts and data checks.

        With `suggest=1`, also the relationships the database, the dictionary and column names suggest going out of a
        base dataset to another base dataset on the same database and not declared yet.
        """
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        seed_dictionary(dataset)
        column_repository = column_dictionary_repository()
        entries = column_repository.list_for_dataset(dataset_id)
        outgoing = [row for row in (self._relationship_row(entry) for entry in entries if entry.is_fk) if row]
        incoming_entries = column_repository.referencing([entry.id for entry in entries]) if entries else []
        incoming = [row for row in (self._relationship_row(entry) for entry in incoming_entries) if row]
        dictionary = dataset_dictionary_repository().get(dataset_id)
        is_base = getattr(dictionary, "dataset_type", None) == BASE_DATASET and not dataset.sql
        payload = {"dataset_id": dataset_id, "is_base": is_base, "outgoing": outgoing, "incoming": incoming}
        if request.args.get("suggest") and is_base:
            payload.update(self._relationship_suggestions(dataset, outgoing))
        return self.response(200, **payload)

    def _relationship_suggestions(self, dataset: SqlaTable, outgoing: list[dict[str, Any]]) -> dict[str, Any]:
        from superset.sql.parse import Table

        tables = base_tables(dataset.database_id)
        for table_dataset in tables:
            seed_dictionary(table_dataset)
        keys = [self._table_keys(table_dataset) for table_dataset in tables]
        database_note = None
        try:
            foreign_keys = {dataset.id: dataset.database.get_foreign_keys(Table(dataset.table_name, dataset.schema))}
        except Exception:
            # The connection may not expose its catalog, or the account may not read it; names still suggest.
            logger.warning("Reading the foreign keys of %s failed", dataset.table_name, exc_info=True)
            foreign_keys, database_note = {}, "Không đọc được khoá ngoại từ database; chỉ gợi ý theo tên cột."
        declared = {(row["from_column"], row["to_dataset_id"], row["to_column"]) for row in outgoing}
        declared_columns = {row["from_column"] for row in outgoing}
        names = {table_dataset.id: table_dataset.table_name for table_dataset in tables}
        suggestions = [
            {
                **item,
                "to_dataset_name": names[item["to_dataset_id"]],
                "replaces": item["from_column"] in declared_columns,
            }
            for item in merged_suggestions(database_suggestions(keys, foreign_keys), naming_suggestions(keys))
            if item["from_dataset_id"] == dataset.id
            and (item["from_column"], item["to_dataset_id"], item["to_column"]) not in declared
        ]
        return {"suggestions": suggestions, "suggestion_note": database_note}

    @expose("/dataset/<int:dataset_id>/relationships/apply", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def apply_relationship_suggestion(self, dataset_id: int):
        """Declare a suggested relationship in the data dictionary and snapshot it as a candidate contract.

        A database foreign key can only point at a key, so its target is marked unique when the dictionary does not
        say so yet; a suggestion from names needs a target the dictionary already declares a key.
        """
        require_admin()
        ensure_dictionary_tables()
        dataset = get_dataset(dataset_id)
        payload = request.get_json(silent=True)
        if dataset is None:
            raise DatasetNotFoundError()
        if not isinstance(payload, dict) or payload.get("source") not in SOURCES:
            raise RelationshipValidationError("The body needs from_column, to_dataset_id, to_column and a source.")
        target_dataset = (
            get_dataset(payload.get("to_dataset_id"))
            if isinstance(payload.get("to_dataset_id"), int)
            else None
        )
        base_ids = {item.id for item in base_tables(dataset.database_id)}
        if dataset_id not in base_ids or target_dataset is None or target_dataset.id not in base_ids:
            raise RelationshipValidationError("Both ends must be base tables on the same database.")
        seed_dictionary(dataset)
        seed_dictionary(target_dataset)
        repository = column_dictionary_repository()
        source_entry = repository.get_for_dataset_column(dataset_id, payload.get("from_column"))
        target_entry = repository.get_for_dataset_column(target_dataset.id, payload.get("to_column"))
        if source_entry is None or target_entry is None:
            raise RelationshipValidationError("Unknown source or target column.")
        target_keys = self._table_keys(target_dataset)
        if target_entry.column_name not in target_keys.unique_columns:
            if payload["source"] != "database":
                raise RelationshipValidationError("Declare the target column a key or unique before using it.")
            target_entry.is_unique = True
        source_entry.is_fk = True
        source_entry.referenced_column = target_entry.id
        repository.flush()
        ends = relationship_ends(source_entry)
        contract = self._snapshot_relationship_candidate(*ends, payload["source"]) if ends else None
        if contract is None:
            raise ApprovedContractExistsError("Revoke the current approved contract before declaring another target.")
        db.session.commit()
        return self.response(201, relationship=self._relationship_row(source_entry))

    @expose("/dataset/<int:dataset_id>/relationships/<int:column_id>/verify", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def verify_relationship(self, dataset_id: int, column_id: int):
        """Check the data bears the relationship out, and store what was found on its contract.

        The queries join two tables, which ChartData of one dataset cannot, so they run read-only on the database's
        engine with a statement timeout; only administrators reach this route.
        """
        require_admin()
        ensure_dictionary_tables()
        source, target = self._relationship_contract_context(dataset_id, column_id)
        contract = self._relationship_contract_for(source.dataset.id, source.entry.column_name)
        if contract is None or contract.status == "revoked":
            raise RelationshipCandidateRequiredError()
        cardinality = relationship_cardinality(source, target)
        if contract.contract_hash != relationship_contract_hash(source, target, cardinality):
            raise RelationshipValidationError("Relationship changed; create a new candidate before checking it.")
        queries = verification_queries(
            source.dataset.schema,
            source.dataset.table_name,
            source.entry.column_name,
            target.dataset.schema,
            target.dataset.table_name,
            target.entry.column_name,
        )
        live_type = {
            (dataset.id, str(column.column_name)): getattr(column, "type", None)
            for dataset in (source.dataset, target.dataset)
            for column in dataset.columns
        }
        type_match = types_match(
            live_type.get((source.dataset.id, source.entry.column_name)),
            live_type.get((target.dataset.id, target.entry.column_name)),
        )
        try:
            with (
                source.dataset.database.get_sqla_engine(schema=source.dataset.schema) as engine,
                engine.connect() as connection,
                connection.begin(),
            ):
                if engine.dialect.name == "postgresql":
                    connection.execute(text(f"SET LOCAL statement_timeout = {VERIFICATION_TIMEOUT_MS}"))
                uniqueness = dict(connection.execute(queries["uniqueness"]).mappings().one())
                target_unique = (uniqueness.get("target_values") or 0) == (uniqueness.get("target_distinct") or 0)
                orphans = dict(connection.execute(queries["orphans"]).mappings().one()) if target_unique else None
                samples = connection.execute(queries["samples"]).scalars().all() if target_unique else []
        except Exception:
            logger.exception(
                "Checking the relationship %s.%s failed", source.dataset.table_name, source.entry.column_name
            )
            return self.response_500(message="Could not run the relationship check on the database.")
        result = verification_result(uniqueness, orphans, list(samples), type_match)
        contract.verification = json.dumps(result, ensure_ascii=False)
        contract.verified_hash = contract.contract_hash
        contract.verified_at = datetime.now(timezone.utc)
        db.session.commit()
        return self.response(200, contract=self._serialize_relationship_contract(contract, source, target))
