from types import SimpleNamespace

import pytest

from text_to_bi.superset_semantic_layer.modules.semantic_query.services.contracts import (
    METRIC_CONTRACT_RULE,
    _safe_connection_identity,
    contract_is_approved_current,
    metric_contract_hash,
    metric_contract_ineligibility,
    metric_contract_state,
    metric_is_eligible_for_contract,
    parse_contract_metric,
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


def _weather_objects(expression):
    dataset, metric = _objects()
    dataset.columns = [
        SimpleNamespace(column_name=name, is_active=True, expression=None)
        for name in ("loai_quan_sat", "nhiet_do_c", "tong_luong_mua_mm")
    ]
    metric.expression = expression
    return dataset, metric


@pytest.mark.parametrize(
    "expression",
    [
        "AVG(CASE WHEN loai_quan_sat = 'DU_BAO_GIO' THEN nhiet_do_c END)",
        "SUM(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' THEN tong_luong_mua_mm END)",
        "COUNT(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0 THEN 1 END)",
        "MAX(CASE WHEN loai_quan_sat IN ('A', 'B') AND NOT nhiet_do_c IS NULL THEN nhiet_do_c ELSE NULL END)",
        'MIN("nhiet_do_c")',
    ],
)
def test_contract_accepts_conditional_aggregates_over_dataset_columns(expression):
    assert metric_is_eligible_for_contract(*_weather_objects(expression))


@pytest.mark.parametrize(
    "expression",
    [
        "AVG(CASE WHEN loai_quan_sat = 'A' THEN nhiet_do_c WHEN loai_quan_sat = 'B' THEN tong_luong_mua_mm END)",
        "AVG(CASE WHEN loai_quan_sat = 'A' THEN nhiet_do_c ELSE tong_luong_mua_mm END)",
        "AVG(CASE WHEN LOWER(loai_quan_sat) = 'a' THEN nhiet_do_c END)",
        "AVG(CASE WHEN loai_quan_sat IN (SELECT secret FROM users) THEN nhiet_do_c END)",
        "AVG(CASE WHEN users.role = 'admin' THEN nhiet_do_c END)",
        "AVG(CASE WHEN unknown_column = 'A' THEN nhiet_do_c END)",
        "AVG(DISTINCT nhiet_do_c)",
        "SUM(nhiet_do_c) FILTER (WHERE loai_quan_sat = 'A')",
        "100.0 * COUNT(CASE WHEN tong_luong_mua_mm > 0 THEN 1 END) / NULLIF(COUNT(nhiet_do_c), 0)",
        "MAX(SUM(nhiet_do_c))",
        "COUNT(*)",
        "COUNT(1)",
        "AVG(nhiet_do_c) OVER (PARTITION BY loai_quan_sat)",
        "{{ metric }}",
    ],
)
def test_contract_rejects_metrics_outside_the_conditional_aggregate_shape(expression):
    assert not metric_is_eligible_for_contract(*_weather_objects(expression))


def test_contract_rejects_a_condition_column_that_is_calculated_or_inactive():
    dataset, metric = _weather_objects("AVG(CASE WHEN loai_quan_sat = 'DU_BAO_GIO' THEN nhiet_do_c END)")
    dataset.columns[0].expression = "UPPER(raw_type)"
    assert not metric_is_eligible_for_contract(dataset, metric)
    dataset.columns[0].expression = None
    dataset.columns[0].is_active = False
    assert not metric_is_eligible_for_contract(dataset, metric)


def test_parse_contract_metric_separates_aggregation_measure_and_condition():
    expression = "COUNT(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0 THEN 1 END)"
    assert parse_contract_metric(expression).as_dict() == {
        "aggregation": "COUNT",
        "measure_column": None,
        "measure_constant": "1",
        "condition": "loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0",
        "columns": ["loai_quan_sat", "tong_luong_mua_mm"],
    }
    assert parse_contract_metric("AVG(nhiet_do_c)").as_dict()["condition"] is None
    assert parse_contract_metric("SUM(a) / COUNT(b)") is None


def test_ineligibility_names_the_offending_column_or_dataset():
    dataset, metric = _weather_objects("AVG(CASE WHEN missing = 'A' THEN nhiet_do_c END)")
    assert metric_contract_ineligibility(dataset, metric) == "Cột missing không có trong dataset."
    metric.expression = "AVG(CASE WHEN loai_quan_sat = 'A' THEN nhiet_do_c END)"
    dataset.columns[0].expression = "UPPER(raw_type)"
    assert metric_contract_ineligibility(dataset, metric) == "Cột loai_quan_sat là cột tính toán."
    dataset.columns[0].expression = None
    assert metric_contract_ineligibility(dataset, metric) is None
    metric.expression = "SUM(a) / COUNT(b)"
    assert metric_contract_ineligibility(dataset, metric) == METRIC_CONTRACT_RULE


def test_metric_contract_state_covers_every_review_stage():
    dataset, metric = _objects()
    assert metric_contract_state(None, dataset, metric) == "not_started"
    expression_hash = metric_contract_hash(dataset, metric)
    contract = SimpleNamespace(
        dataset_id=dataset.id, metric_id=metric.id, status="candidate", expression_hash=expression_hash
    )
    assert metric_contract_state(contract, dataset, metric) == "candidate"
    contract.status = "approved"
    assert metric_contract_state(contract, dataset, metric) == "approved"
    metric.expression = "SUM(temperature_c)"
    assert metric_contract_state(contract, dataset, metric) == "outdated"
    contract.status = "candidate"
    assert metric_contract_state(contract, dataset, metric) == "outdated"
    contract.status = "revoked"
    assert metric_contract_state(contract, dataset, metric) == "revoked"
    metric.expression = "SUM(temperature_c) / 2"
    assert metric_contract_state(None, dataset, metric) == "ineligible"


def test_a_virtual_dataset_is_eligible_but_editing_its_sql_voids_the_approval():
    dataset, metric = _objects()
    dataset.sql = "SELECT city, temperature_c FROM weather_daily"
    assert metric_is_eligible_for_contract(dataset, metric)
    approved_hash = metric_contract_hash(dataset, metric)
    dataset.sql = "SELECT city, temperature_c FROM weather_daily WHERE city = 'Hue'"
    assert metric_contract_hash(dataset, metric) != approved_hash


def test_contract_rejects_computed_metric_column():
    dataset, metric = _objects()
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
