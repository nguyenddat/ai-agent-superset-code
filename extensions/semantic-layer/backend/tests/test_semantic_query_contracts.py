from types import SimpleNamespace

from text_to_bi.superset_semantic_layer.modules.semantic_query.services.contracts import build_preview_contract


def _dataset(*, expression: str = 'AVG("temperature_c")'):
    return SimpleNamespace(
        id=42,
        table_name="weather_daily",
        schema="analytics",
        database=SimpleNamespace(db_engine_spec=SimpleNamespace(engine="postgresql")),
        columns=[SimpleNamespace(column_name="city_id"), SimpleNamespace(column_name="temperature_c")],
        metrics=[SimpleNamespace(metric_name="average_temperature", expression=expression)],
    )


def test_builds_an_ephemeral_single_dataset_contract_from_curated_metadata():
    contract = build_preview_contract(_dataset(), [SimpleNamespace(column_name="city_id")])

    assert contract == {
        "dataset": {"name": "weather_daily", "table": "analytics.weather_daily", "dialect": "postgresql"},
        "metrics": [
            {
                "name": "average_temperature",
                "dataset": "weather_daily",
                "eligible_for_preview": True,
                "aggregation": "avg",
                "column": "temperature_c",
            }
        ],
        "dimensions": [
            {"name": "city_id", "dataset": "weather_daily", "eligible_for_preview": True, "column": "city_id"}
        ],
        "contract_source": "curated_superset_metric_and_dictionary",
    }


def test_excludes_metrics_that_cannot_be_proven_safe_single_column_aggregates():
    assert build_preview_contract(_dataset(expression="SUM(temperature_c + 1)"), []) ["metrics"] == []


def test_excludes_metrics_with_names_that_cannot_be_used_as_quoted_sql_aliases():
    dataset = _dataset()
    dataset.metrics[0].metric_name = "average temperature; drop"

    assert build_preview_contract(dataset, [])["metrics"] == []

