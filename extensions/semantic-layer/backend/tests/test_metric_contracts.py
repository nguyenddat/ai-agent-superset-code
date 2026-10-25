from types import SimpleNamespace

import pytest

from text_to_bi.superset_semantic_layer.modules.semantic_query.contracts import (
    _safe_connection_identity,
    contract_is_approved_current,
    metric_contract_hash,
    metric_is_eligible_for_contract,
)


def _objects():
    dataset = SimpleNamespace(
        id=7,
        catalog="analytics",
        schema="public",
        table_name="weather_daily",
        sql=None,
        database=SimpleNamespace(id=3, database_name="warehouse", sqlalchemy_uri="postgresql://user:secret@db:5432/warehouse"),
        columns=[SimpleNamespace(column_name="temperature_c", is_active=True, expression=None)],
    )
    metric = SimpleNamespace(id=19, metric_name="average_temperature", expression="AVG(temperature_c)")
    return dataset, metric


def test_metric_contract_hash_binds_dataset_metric_and_live_definition():
    dataset, metric = _objects()
    original = metric_contract_hash(dataset, metric)

    metric.expression = "AVG(temperature_f)"
    assert metric_contract_hash(dataset, metric) != original
    metric.expression = "AVG(temperature_c)"
    dataset.table_name = "weather_monthly"
    assert metric_contract_hash(dataset, metric) != original
    dataset.table_name = "weather_daily"
    dataset.database.id = 4
    assert metric_contract_hash(dataset, metric) != original


def test_hash_never_contains_connection_secret_and_binds_metric_column_expression():
    dataset, metric = _objects()
    assert "secret" not in str(_safe_connection_identity(dataset.database))
    original = metric_contract_hash(dataset, metric)
    dataset.columns[0].expression = "temperature_c::numeric"
    assert metric_contract_hash(dataset, metric) != original


@pytest.mark.parametrize("expression", ["SUM(temperature_c + 1)", "SUM((SELECT secret FROM users))"])
def test_contract_rejects_unsafe_metric_expressions(expression):
    dataset, metric = _objects()
    metric.expression = expression
    assert not metric_is_eligible_for_contract(dataset, metric)


def test_contract_rejects_virtual_dataset_and_computed_metric_column():
    dataset, metric = _objects()
    dataset.sql = "SELECT * FROM weather_daily"
    assert not metric_is_eligible_for_contract(dataset, metric)
    dataset.sql = None
    dataset.columns[0].expression = "temperature_c + 1"
    assert not metric_is_eligible_for_contract(dataset, metric)


def test_only_an_approved_current_contract_is_executable():
    dataset, metric = _objects()
    contract = SimpleNamespace(
        dataset_id=dataset.id,
        metric_id=metric.id,
        status="approved",
        expression_hash=metric_contract_hash(dataset, metric),
    )

    assert contract_is_approved_current(contract, dataset, metric)
    contract.status = "candidate"
    assert not contract_is_approved_current(contract, dataset, metric)
    contract.status = "revoked"
    assert not contract_is_approved_current(contract, dataset, metric)
    contract.status = "approved"
    metric.metric_name = "changed_name"
    assert not contract_is_approved_current(contract, dataset, metric)
    metric.metric_name = "average_temperature"
    contract.dataset_id = 99
    assert not contract_is_approved_current(contract, dataset, metric)
