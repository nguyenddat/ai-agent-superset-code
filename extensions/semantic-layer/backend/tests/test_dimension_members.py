from types import SimpleNamespace

from text_to_bi.superset_semantic_layer.modules.semantic_query.members import (
    MAX_MEMBERS,
    build_members_payload,
    labelled_key_columns,
    members_from_rows,
)


def _column(name, expression=None, groupby=True, filterable=True, is_active=True):
    return SimpleNamespace(
        column_name=name, expression=expression, groupby=groupby, filterable=filterable, is_active=is_active,
    )


def _dataset(columns):
    return SimpleNamespace(id=12, table_name="fact_weather", columns=columns)


def test_a_calculated_column_reading_one_physical_column_labels_it():
    dataset = _dataset([
        _column("city_key"),
        _column("day_key"),
        _column("city_name", "(SELECT d.name FROM dim_city d WHERE d.city_key = fact_weather.city_key)"),
        _column("city_and_day", "fact_weather.city_key || fact_weather.day_key"),
        _column("hidden_name", "(SELECT 1 WHERE fact_weather.city_key = 1)", groupby=False),
        _column("constant", "'x'"),
    ])

    assert labelled_key_columns(dataset) == [("city_key", "city_name")]


def test_the_payload_reads_only_the_key_and_label_with_a_bounded_row_limit():
    payload = build_members_payload(_dataset([]), "city_key", "city_name")

    query = payload["queries"][0]
    assert payload["datasource"] == {"id": 12, "type": "table"}
    assert query["columns"] == ["city_key", "city_name"]
    assert query["row_limit"] == MAX_MEMBERS + 1


def test_members_are_unique_labelled_pairs_sorted_by_label():
    rows = [
        {"city_key": 2, "city_name": "Hue"},
        {"city_key": 1, "city_name": "Ha Noi"},
        {"city_key": 1, "city_name": "Ha Noi"},
        {"city_key": None, "city_name": "Unknown"},
        {"city_key": 3, "city_name": None},
    ]

    assert members_from_rows(rows, "city_key", "city_name") == [
        {"value": 1, "label": "Ha Noi"},
        {"value": 2, "label": "Hue"},
    ]
