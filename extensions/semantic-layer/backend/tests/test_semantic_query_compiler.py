import pytest

from text_to_bi.superset_semantic_layer.modules.semantic_query.services.compiler import (
    SemanticQueryError,
    compile_semantic_query,
)

DATASET = {"name": "weather_daily", "table": "analytics.weather_daily", "dialect": "postgres"}
METRICS = [
    {
        "name": "average_temperature",
        "dataset": "weather_daily",
        "approved": True,
        "aggregation": "avg",
        "column": "nhiet_do_c",
    }
]
DIMENSIONS = [{"name": "city", "dataset": "weather_daily", "approved": True, "column": "thanh_pho_id"}]


def compile_query(request: dict) -> dict:
    return compile_semantic_query(DATASET, METRICS, DIMENSIONS, request)


def test_compiles_a_deterministic_single_dataset_query_with_provenance():
    request = {
        "metric": "average_temperature",
        "dimensions": ["city"],
        "filters": [{"dimension": "city", "operator": "=", "value": 7}],
    }

    first = compile_query(request)
    second = compile_query(request)

    assert first == second
    assert first == {
        "sql": 'SELECT "thanh_pho_id" AS "city", AVG("nhiet_do_c") AS "average_temperature"\n'
        'FROM "analytics"."weather_daily"\n'
        'WHERE "thanh_pho_id" = %(p0)s\n'
        'GROUP BY "thanh_pho_id"',
        "parameters": {"p0": 7},
        "paramstyle": "pyformat",
        "provenance": {
            "dataset": "weather_daily",
            "metric": {"name": "average_temperature", "aggregation": "AVG", "column": "nhiet_do_c"},
            "dimensions": [{"name": "city", "column": "thanh_pho_id"}],
            "filters": [{"dimension": "city", "column": "thanh_pho_id", "operator": "="}],
        },
    }


def test_requires_an_approved_metric():
    with pytest.raises(SemanticQueryError, match="approved metric"):
        compile_query({"metric": "total_rain", "dimensions": []})

    unapproved_metrics = [{**METRICS[0], "approved": False}]
    with pytest.raises(SemanticQueryError, match="approved metric"):
        compile_semantic_query(
            DATASET, unapproved_metrics, DIMENSIONS, {"metric": "average_temperature", "dimensions": []}
        )


def test_indexes_only_approved_definitions_for_the_requested_dataset():
    unrelated_metric = {**METRICS[0], "name": "other_metric", "dataset": "other_dataset"}
    unapproved_metric = {**METRICS[0], "name": "private_metric", "approved": False}
    unrelated_dimension = {**DIMENSIONS[0], "name": "other_dimension", "dataset": "other_dataset"}
    unapproved_dimension = {**DIMENSIONS[0], "name": "private_dimension", "approved": False}

    result = compile_semantic_query(
        DATASET,
        METRICS + [unrelated_metric, unapproved_metric],
        DIMENSIONS + [unrelated_dimension, unapproved_dimension],
        {"metric": "average_temperature", "dimensions": ["city"]},
    )

    assert result["provenance"]["metric"]["name"] == "average_temperature"
    assert result["provenance"]["dimensions"] == [{"name": "city", "column": "thanh_pho_id"}]


@pytest.mark.parametrize(
    "query_request",
    [
        {"metric": "private_metric", "dimensions": []},
        {"metric": "average_temperature", "dimensions": ["private_dimension"]},
    ],
)
def test_rejects_names_excluded_from_the_approved_dataset_index(query_request: dict):
    metrics = METRICS + [{**METRICS[0], "name": "private_metric", "approved": False}]
    dimensions = DIMENSIONS + [{**DIMENSIONS[0], "name": "private_dimension", "approved": False}]

    with pytest.raises(SemanticQueryError, match="approved"):
        compile_semantic_query(DATASET, metrics, dimensions, query_request)


@pytest.mark.parametrize(
    "query_request",
    [
        {"metric": "average_temperature", "dimensions": ["country"]},
        {"metric": "average_temperature", "dimensions": ["city"], "filters": [{"dimension": "country", "value": "VN"}]},
    ],
)
def test_rejects_unknown_or_unapproved_dimensions(query_request: dict):
    with pytest.raises(SemanticQueryError, match="approved dimension"):
        compile_query(query_request)


@pytest.mark.parametrize(
    "contract",
    [
        ({**DATASET, "table": "weather_daily; DROP TABLE users"}, METRICS, DIMENSIONS),
        (DATASET, [{**METRICS[0], "column": "nhiet_do_c) --"}], DIMENSIONS),
        (DATASET, METRICS, [{**DIMENSIONS[0], "column": "thanh_pho_id; DROP TABLE users"}]),
    ],
)
def test_rejects_invalid_contract_identifiers(contract: tuple[dict, list[dict], list[dict]]):
    dataset, metrics, dimensions = contract
    with pytest.raises(SemanticQueryError, match="identifier"):
        compile_semantic_query(dataset, metrics, dimensions, {"metric": "average_temperature", "dimensions": ["city"]})


def test_binds_filter_values_and_never_interpolates_them():
    value = "x' OR 1=1 --"
    result = compile_query(
        {"metric": "average_temperature", "dimensions": [], "filters": [{"dimension": "city", "value": value}]}
    )

    assert result["parameters"] == {"p0": value}
    assert value not in result["sql"]
    assert 'WHERE "thanh_pho_id" = %(p0)s' in result["sql"]


@pytest.mark.parametrize("field", ["limit", "order", "time_grain", "sql"])
def test_rejects_unknown_top_level_request_fields(field: str):
    request = {"metric": "average_temperature", "dimensions": [], field: "ignored"}

    with pytest.raises(SemanticQueryError, match="unknown request field"):
        compile_query(request)


@pytest.mark.parametrize("field", ["column", "sql", "limit"])
def test_rejects_unknown_filter_fields(field: str):
    request = {
        "metric": "average_temperature",
        "dimensions": [],
        "filters": [{"dimension": "city", "value": 7, field: "ignored"}],
    }

    with pytest.raises(SemanticQueryError, match="unknown filter field"):
        compile_query(request)


@pytest.mark.parametrize("value", [None, [], {}, float("nan"), float("inf"), float("-inf")])
def test_rejects_non_scalar_or_non_finite_filter_values(value):
    request = {"metric": "average_temperature", "dimensions": [], "filters": [{"dimension": "city", "value": value}]}

    with pytest.raises(SemanticQueryError, match="safe scalar"):
        compile_query(request)


@pytest.mark.parametrize("value", ["Hanoi", 7, 3.5, True, False])
def test_binds_safe_scalar_filter_values(value):
    result = compile_query(
        {"metric": "average_temperature", "dimensions": [], "filters": [{"dimension": "city", "value": value}]}
    )

    assert result["parameters"] == {"p0": value}


@pytest.mark.parametrize(
    "query_request",
    [
        {"metric": "average_temperature", "dimensions": [], "joins": [{"dataset": "cities"}]},
        {"metric": "average_temperature", "dimensions": [{"name": "city", "dataset": "cities"}]},
    ],
)
def test_rejects_joins_and_cross_dataset_requests(query_request: dict):
    with pytest.raises(SemanticQueryError, match="single dataset"):
        compile_query(query_request)
