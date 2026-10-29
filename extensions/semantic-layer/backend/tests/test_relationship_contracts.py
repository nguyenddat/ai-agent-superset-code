from dataclasses import replace
from types import SimpleNamespace

import pytest

from text_to_bi.superset_semantic_layer.modules.semantic_query.services.relationships import (
    RelationshipEnd,
    relationship_cardinality,
    relationship_contract_hash,
    relationship_is_approved_current,
)


def _ends():
    database = SimpleNamespace(id=3, database_name="warehouse", sqlalchemy_uri="postgresql://user:secret@db/warehouse")
    source = SimpleNamespace(
        id=7,
        catalog="analytics",
        schema="public",
        table_name="weather_daily",
        sql=None,
        database=database,
        columns=[SimpleNamespace(column_name="city_id", is_active=True, expression=None, type="INTEGER")],
    )
    target = SimpleNamespace(
        id=8,
        catalog="analytics",
        schema="public",
        table_name="cities",
        sql=None,
        database=database,
        columns=[SimpleNamespace(column_name="id", is_active=True, expression=None, type="INTEGER")],
    )
    return (
        RelationshipEnd(
            source,
            SimpleNamespace(column_name="city_id", data_type="INTEGER", is_fk=True, is_pk=False, is_unique=False),
            0,
        ),
        RelationshipEnd(
            target, SimpleNamespace(column_name="id", data_type="INTEGER", is_fk=False, is_pk=True, is_unique=False), 1
        ),
    )


def test_relationship_contract_is_many_to_one_and_hash_has_no_connection_secret():
    source, target = _ends()
    cardinality = relationship_cardinality(source, target)
    contract_hash = relationship_contract_hash(source, target, cardinality)

    assert cardinality == "many_to_one"
    assert "secret" not in contract_hash
    contract = SimpleNamespace(
        status="approved",
        from_dataset_id=source.dataset.id,
        from_column=source.entry.column_name,
        to_dataset_id=target.dataset.id,
        to_column=target.entry.column_name,
        cardinality=cardinality,
        contract_hash=contract_hash,
    )
    assert relationship_is_approved_current(contract, source, target)


@pytest.mark.parametrize("change", ["target_type", "target_key", "source_fk", "target_live"])
def test_relationship_contract_becomes_stale_when_live_safety_properties_change(change):
    source, target = _ends()
    cardinality = relationship_cardinality(source, target)
    contract = SimpleNamespace(
        status="approved",
        from_dataset_id=source.dataset.id,
        from_column=source.entry.column_name,
        to_dataset_id=target.dataset.id,
        to_column=target.entry.column_name,
        cardinality=cardinality,
        contract_hash=relationship_contract_hash(source, target, cardinality),
    )
    if change == "target_type":
        target.dataset.columns[0].type = "BIGINT"
    elif change == "target_key":
        target.entry.is_pk = False
    elif change == "source_fk":
        source.entry.is_fk = False
    else:
        target.dataset.columns[0].is_active = False

    assert not relationship_is_approved_current(contract, source, target)


def test_relationship_rejects_cross_database_composite_target_and_non_fk_source():
    source, target = _ends()
    target.dataset.database = SimpleNamespace(id=4)
    with pytest.raises(ValueError, match="same database"):
        relationship_cardinality(source, target)
    target.dataset.database = source.dataset.database
    target = replace(target, pk_count=2)
    with pytest.raises(ValueError, match="unique"):
        relationship_cardinality(source, target)
    target = replace(target, pk_count=1)
    source.entry.is_fk = False
    with pytest.raises(ValueError, match="foreign key"):
        relationship_cardinality(source, target)
