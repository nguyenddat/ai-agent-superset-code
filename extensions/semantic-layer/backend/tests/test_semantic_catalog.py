from types import SimpleNamespace

from text_to_bi.superset_semantic_layer.modules.semantic_query.catalog import build_semantic_catalog
from text_to_bi.superset_semantic_layer.modules.semantic_query.contracts import metric_contract_hash
from text_to_bi.superset_semantic_layer.modules.semantic_query.relationships import (
    RelationshipEnd,
    relationship_contract_hash,
)


def _dataset(dataset_id, name, columns, metrics):
    return SimpleNamespace(
        id=dataset_id,
        table_name=name,
        catalog="analytics",
        schema="public",
        sql=None,
        database=SimpleNamespace(id=1, database_name="warehouse"),
        columns=columns,
        metrics=metrics,
    )


def test_catalog_hides_inaccessible_stale_and_sensitive_contract_details():
    city = SimpleNamespace(column_name="city", is_active=True, expression=None, groupby=True, filterable=True, type="TEXT")
    secret = SimpleNamespace(column_name="secret", is_active=True, expression="decrypt(secret)", groupby=True, filterable=True)
    metric = SimpleNamespace(id=19, metric_name="average_temperature", expression="AVG(city)", verbose_name="Average", description="Safe")
    allowed = _dataset(7, "weather", [city, secret], [metric])
    denied = _dataset(8, "private", [city], [metric])
    current = SimpleNamespace(
        dataset_id=7, metric_id=19, status="approved", expression_hash=metric_contract_hash(allowed, metric), expression="AVG(city)"
    )
    stale = SimpleNamespace(dataset_id=8, metric_id=19, status="approved", expression_hash="stale", expression="AVG(city)")

    result = build_semantic_catalog({7: allowed, 8: denied}, [current, stale], [], lambda dataset: dataset.id == 7, 1000)

    assert result["datasets"] == [
        {
            "id": 7,
            "name": "weather",
            "metrics": [{
                "metric_id": 19, "metric_name": "average_temperature", "verbose_name": "Average", "description": "Safe",
                "d3format": None,
            }],
            "dimensions": [{"name": "city", "groupby": True, "filterable": True}],
        }
    ]
    assert "expression" not in str(result)
    assert "hash" not in str(result)


def test_catalog_returns_only_current_relationships_accessible_on_both_ends():
    source_column = SimpleNamespace(column_name="city_id", is_active=True, expression=None, groupby=True, filterable=True, type="INTEGER")
    target_column = SimpleNamespace(column_name="id", is_active=True, expression=None, groupby=True, filterable=True, type="INTEGER")
    source = _dataset(7, "weather", [source_column], [])
    target = _dataset(8, "cities", [target_column], [])
    source_end = RelationshipEnd(source, SimpleNamespace(column_name="city_id", data_type="INTEGER", is_fk=True, is_pk=False, is_unique=False), 0)
    target_end = RelationshipEnd(target, SimpleNamespace(column_name="id", data_type="INTEGER", is_fk=False, is_pk=True, is_unique=False), 1)
    contract = SimpleNamespace(
        id=5,
        from_dataset_id=7,
        from_column="city_id",
        to_dataset_id=8,
        to_column="id",
        cardinality="many_to_one",
        status="approved",
        contract_hash=relationship_contract_hash(source_end, target_end, "many_to_one"),
    )

    visible = build_semantic_catalog({7: source, 8: target}, [], [(contract, source_end, target_end)], lambda _: True, 1000)
    hidden = build_semantic_catalog({7: source, 8: target}, [], [(contract, source_end, target_end)], lambda d: d.id == 7, 1000)

    assert visible["relationships"] == [
        {"id": 5, "from_dataset_id": 7, "from_column": "city_id", "to_dataset_id": 8, "to_column": "id", "cardinality": "many_to_one", "executable": False}
    ]
    assert hidden["relationships"] == []
    assert hidden["datasets"] == []


def test_catalog_adds_business_context_only_to_visible_metrics():
    metric = SimpleNamespace(
        id=19, metric_name="max_temperature", expression="MAX(temperature)", verbose_name="Max", description=None,
        d3format=",.1f",
    )
    temperature = SimpleNamespace(
        column_name="temperature", is_active=True, expression=None, groupby=False, filterable=True, type="FLOAT"
    )
    allowed = _dataset(7, "weather", [temperature], [metric])
    denied = _dataset(8, "private", [temperature], [metric])
    contracts = [
        SimpleNamespace(dataset_id=dataset.id, metric_id=19, status="approved", expression_hash=metric_contract_hash(dataset, metric))
        for dataset in (allowed, denied)
    ]
    asked = []

    def metric_details(dataset_id, metric_id):
        asked.append((dataset_id, metric_id))
        return {"business_definition": "Highest daily temperature.", "unit": "°C", "glossary_terms": []}

    result = build_semantic_catalog({7: allowed, 8: denied}, contracts, [], lambda d: d.id == 7, 1000, metric_details)

    assert asked == [(7, 19)]
    assert result["datasets"][0]["metrics"] == [{
        "metric_id": 19, "metric_name": "max_temperature", "verbose_name": "Max", "description": None, "d3format": ",.1f",
        "business_definition": "Highest daily temperature.", "unit": "°C", "glossary_terms": [],
    }]
    assert "MAX(" not in str(result)
