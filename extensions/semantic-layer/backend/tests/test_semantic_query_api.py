from types import SimpleNamespace

import pytest

from text_to_bi.superset_semantic_layer.modules.semantic_query.contracts import (
    build_metric_chart_payload,
    execute_approved_chart_query,
    metric_contract_hash,
)


def _dataset():
    column = lambda name: SimpleNamespace(
        column_name=name, is_active=True, groupby=True, filterable=True, expression=None
    )
    return SimpleNamespace(id=7, columns=[column("city"), column("temperature_c")])


def test_chart_payload_uses_saved_metric_and_hard_server_cap():
    payload = build_metric_chart_payload(
        _dataset(),
        SimpleNamespace(metric_name="average_temperature"),
        {"dimensions": ["city"], "filters": [{"column": "city", "operator": "==", "value": "Hanoi"}]},
        1000,
    )

    query = payload["queries"][0]
    assert query["metrics"] == ["average_temperature"]
    assert query["row_limit"] == 1001
    assert query["columns"] == ["city"]


@pytest.mark.parametrize(
    "body",
    [
        {"joins": []},
        {"dimensions": ["missing"], "filters": []},
        {"dimensions": [], "filters": [{"column": "city", "operator": "sql", "value": "x"}]},
    ],
)
def test_chart_payload_rejects_joins_unknown_columns_and_arbitrary_sql(body):
    with pytest.raises(ValueError):
        build_metric_chart_payload(_dataset(), SimpleNamespace(metric_name="average_temperature"), body, 1000)


def test_tablecolumn_shaped_columns_use_only_real_capability_fields():
    dataset = _dataset()
    dataset.columns[0].groupby = False
    with pytest.raises(ValueError, match="not available"):
        build_metric_chart_payload(dataset, SimpleNamespace(metric_name="average_temperature"), {"dimensions": ["city"]}, 1000)


@pytest.mark.parametrize(
    "filter_",
    [
        {"column": "city", "operator": "IN", "value": "Hanoi"},
        {"column": "city", "operator": "NOT IN", "value": "Hanoi"},
        {"column": "city", "operator": "==", "value": ["Hanoi"]},
        {"column": "city", "operator": "!=", "value": None},
    ],
)
def test_chart_payload_requires_operator_compatible_non_null_filter_values(filter_):
    with pytest.raises(ValueError):
        build_metric_chart_payload(
            _dataset(), SimpleNamespace(metric_name="average_temperature"), {"dimensions": [], "filters": [filter_]}, 1000
        )


def test_chart_payload_allows_a_bounded_scalar_list_for_membership_filters():
    payload = build_metric_chart_payload(
        _dataset(),
        SimpleNamespace(metric_name="average_temperature"),
        {"dimensions": [], "filters": [{"column": "city", "operator": "IN", "value": ["Hanoi", "Hue"]}]},
        1000,
    )

    assert payload["queries"][0]["filters"] == [{"col": "city", "op": "IN", "val": ["Hanoi", "Hue"]}]


def test_chart_payload_rejects_calculated_columns_in_dimensions_and_filters():
    dataset = _dataset()
    dataset.columns[0].expression = "UPPER(city)"

    with pytest.raises(ValueError, match="calculated"):
        build_metric_chart_payload(dataset, SimpleNamespace(metric_name="average_temperature"), {"dimensions": ["city"]}, 1000)
    with pytest.raises(ValueError, match="calculated"):
        build_metric_chart_payload(
            dataset,
            SimpleNamespace(metric_name="average_temperature"),
            {"dimensions": [], "filters": [{"column": "city", "operator": "==", "value": "Hanoi"}]},
            1000,
        )


@pytest.mark.parametrize(
    "body",
    [
        {"dimensions": ["city"] * 51},
        {"dimensions": [], "filters": [{"column": "city", "operator": "==", "value": ["x"] * 101}]},
        {"dimensions": [], "filters": [{"column": "city", "operator": "==", "value": {"sql": "x"}}]},
        {"dimensions": [], "filters": [{"column": "city", "operator": "==", "value": "x" * 1025}]},
        {"dimensions": [], "filters": [{"column": "city", "operator": "==", "value": "x"}] * 51},
    ],
)
def test_chart_payload_bounds_filter_and_dimension_input(body):
    with pytest.raises(ValueError):
        build_metric_chart_payload(_dataset(), SimpleNamespace(metric_name="average_temperature"), body, 1000)


@pytest.mark.parametrize("status, stale", [("candidate", False), ("revoked", False), ("approved", True)])
def test_unapproved_or_stale_contract_never_calls_chartdata_runner(status, stale):
    dataset = _dataset()
    dataset.catalog = dataset.schema = dataset.table_name = dataset.sql = None
    dataset.database = SimpleNamespace(database_name="warehouse")
    metric = SimpleNamespace(id=4, metric_name="average_temperature", expression="AVG(temperature_c)")
    contract = SimpleNamespace(
        dataset_id=dataset.id,
        metric_id=metric.id,
        status=status,
        expression_hash="stale" if stale else metric_contract_hash(dataset, metric),
    )
    calls = []

    with pytest.raises(PermissionError):
        execute_approved_chart_query(contract, dataset, metric, {"dimensions": []}, 1000, calls.append)
    assert calls == []


def test_only_the_supplied_chartdata_runner_validates_and_runs_after_approval():
    dataset = _dataset()
    dataset.catalog = dataset.schema = dataset.table_name = dataset.sql = None
    dataset.database = SimpleNamespace(database_name="warehouse")
    metric = SimpleNamespace(id=4, metric_name="average_temperature", expression="AVG(temperature_c)")
    contract = SimpleNamespace(
        dataset_id=dataset.id,
        metric_id=metric.id,
        status="approved",
        expression_hash=metric_contract_hash(dataset, metric),
    )
    calls = []

    result = execute_approved_chart_query(contract, dataset, metric, {"dimensions": []}, 1000, lambda payload: calls.append(payload) or "ran")
    assert result == "ran"
    assert calls[0]["queries"][0]["row_limit"] == 1001


@pytest.mark.parametrize(
    "status, stale, allowed", [("candidate", False, True), ("candidate", True, False), ("revoked", False, False)]
)
def test_candidate_preview_runs_only_when_granted_and_unchanged(status, stale, allowed):
    dataset = _dataset()
    dataset.catalog = dataset.schema = dataset.table_name = dataset.sql = None
    dataset.database = SimpleNamespace(database_name="warehouse")
    metric = SimpleNamespace(id=4, metric_name="average_temperature", expression="AVG(temperature_c)")
    contract = SimpleNamespace(
        dataset_id=dataset.id,
        metric_id=metric.id,
        status=status,
        expression_hash="stale" if stale else metric_contract_hash(dataset, metric),
    )

    def run(payload):
        return "ran"

    with pytest.raises(PermissionError):
        execute_approved_chart_query(contract, dataset, metric, {"dimensions": []}, 1000, run)
    query = {"dimensions": []}
    if allowed:
        assert execute_approved_chart_query(contract, dataset, metric, query, 1000, run, allow_candidate=True) == "ran"
    else:
        with pytest.raises(PermissionError):
            execute_approved_chart_query(contract, dataset, metric, query, 1000, run, allow_candidate=True)
