import pytest

from text_to_bi.superset_ai_agent.modules.chat.query import (
    QueryPlanError,
    combined_result,
    plan_query,
    result_for_answer,
)

COLUMNS = [
    {"name": "ngay", "label": "Ngày", "type": "DATE", "temporal": True, "groupby": True, "filterable": True},
    {"name": "thanh_pho_key", "type": "INTEGER", "groupby": True, "filterable": True},
    {"name": "toc_do_gio_toi_da_kmh", "type": "NUMERIC(6,2)", "groupby": False, "filterable": True},
]
DATASETS = [{"id": 12, "columns": COLUMNS}]
METRICS = [
    {"dataset_id": 12, "metric_id": 20, "name": "Tổng lượng mưa", "metric_name": "tong_luong_mua", "unit": "mm"},
    {"dataset_id": 12, "metric_id": 23, "name": "Tốc độ gió tối đa", "metric_name": "toc_do_gio_toi_da"},
    {"dataset_id": 9, "metric_id": 5, "name": "Khác", "metric_name": "khac"},
]


def _plan(**changes):
    return {"dataset_id": 12, "metric_ids": [20], "dimensions": [], "filters": [], **changes}


def test_a_plan_without_dimensions_is_a_number_and_a_region_filter_is_a_list():
    place = {"column": "thanh_pho_key", "operator": "IN", "value": "3", "source": "place"}
    planned = plan_query(_plan(filters=[place], scope=" Miền Trung "), DATASETS, METRICS, [])

    assert (planned.presentation, planned.scope) == ("number", "Miền Trung")
    assert planned.request_body() == {
        "dimensions": [], "filters": [{"column": "thanh_pho_key", "operator": "IN", "value": [3]}],
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"dataset_id": 99},
        {"metric_ids": [5]},
        {"dimensions": ["toc_do_gio_toi_da_kmh"]},
        {"filters": [{"column": "ngay", "operator": "LIKE", "value": "2026%"}]},
        {"filters": [{"column": "toc_do_gio_toi_da_kmh", "operator": ">=", "value": "mạnh"}]},
        {"filters": [{"column": "ngay", "operator": "==", "value": ["2026-10-01", "2026-10-02"]}]},
        {"filters": [{"column": "ngay", "operator": ">=", "value": ""}]},
    ],
)
def test_a_plan_outside_the_catalog_is_refused(changes):
    with pytest.raises(QueryPlanError):
        plan_query(_plan(**changes), DATASETS, METRICS, [])


def test_a_rule_that_cannot_be_a_filter_is_refused_and_one_on_another_dataset_is_noted():
    with pytest.raises(QueryPlanError):
        plan_query(_plan(), DATASETS, METRICS, [{"name": "Ngày bão", "dataset_id": 12, "filters": None}])

    planned = plan_query(_plan(), DATASETS, METRICS, [{"name": "Khác", "dataset_id": 9, "filters": []}])
    assert planned.filters == [] and planned.notes


def test_each_metric_becomes_a_column_of_one_table_by_dimension():
    planned = plan_query(_plan(metric_ids=[20, 23], dimensions=["ngay"]), DATASETS, METRICS, [])
    answers = [
        {"rows": [{"ngay": "Mon, 19 Oct 2026 00:00:00 GMT", "tong_luong_mua": "12.5000"}], "truncated": False},
        {"rows": [{"ngay": "Mon, 19 Oct 2026 00:00:00 GMT", "toc_do_gio_toi_da": "16.8000"}], "truncated": True},
    ]

    result = combined_result(planned, answers)

    assert result["rows"] == [{"ngay": "2026-10-19", "tong_luong_mua": 12.5, "toc_do_gio_toi_da": 16.8}]
    assert (result["presentation"], result["row_count"], result["truncated"]) == ("table", 1, True)
    assert [metric["label"] for metric in result["metrics"]] == ["Tổng lượng mưa", "Tốc độ gió tối đa"]


def test_the_answer_reads_capped_rows():
    planned = plan_query(_plan(dimensions=["ngay"]), DATASETS, METRICS, [])
    rows = [{"ngay": f"2026-{month:02d}-{day:02d}", "tong_luong_mua": 1} for month in (1, 2, 3) for day in range(1, 29)]

    shown = result_for_answer(combined_result(planned, [{"rows": rows}]))

    assert (len(shown["rows"]), shown["row_count"], shown["rows_omitted"]) == (60, 84, 24)


def test_keys_with_labelled_values_are_shown_by_their_labels():
    labelled = [{
        "column": "thanh_pho_key", "label": "Thành phố",
        "values": [{"value": 1, "label": "Ha Noi"}, {"value": 2, "label": "Hue"}],
    }]
    datasets = [{"id": 12, "columns": COLUMNS, "labelled_values": labelled}]
    place = {"column": "thanh_pho_key", "operator": "IN", "value": [1.0, "2"], "source": "place"}
    planned = plan_query(_plan(dimensions=["thanh_pho_key"], filters=[place]), datasets, METRICS, [])

    result = combined_result(planned, [{"rows": [{"thanh_pho_key": 2, "tong_luong_mua": 3}]}])

    assert planned.request_body()["filters"] == [{"column": "thanh_pho_key", "operator": "IN", "value": [1, 2]}]
    assert result["filters"][0]["shown_value"] == ["Ha Noi", "Hue"]
    assert result["rows"] == [{"thanh_pho_key": "Hue", "tong_luong_mua": 3}]
    assert "value_labels" not in result["dimensions"][0] and result["dimensions"][0]["label"] == "Thành phố"


def test_an_aggregate_over_no_rows_is_no_data_and_each_query_is_kept_for_the_page():
    planned = plan_query(_plan(), DATASETS, METRICS, [])

    result = combined_result(planned, [{"rows": [{"tong_luong_mua": None}], "sql": "SELECT SUM(...)"}])

    assert (result["rows"], result["row_count"]) == ([], 0)
    assert result["queries"] == [{
        "metric": "Tổng lượng mưa", "dataset_id": 12, "metric_id": 20, "request": planned.request_body(),
        "sql": "SELECT SUM(...)",
    }]
    assert "queries" not in result_for_answer(result)


def test_a_key_is_named_by_the_labels_that_tell_its_values_apart():
    cities = {"column": "thanh_pho_key", "values": [{"value": 1, "label": "Ha Noi"}, {"value": 2, "label": "Hue"}]}
    regions = {"column": "thanh_pho_key", "values": [{"value": 1, "label": "Bac"}, {"value": 2, "label": "Bac"}]}
    place = {"column": "thanh_pho_key", "operator": "==", "value": 1, "source": "place"}
    for labelled in ([cities, regions], [regions, cities]):
        datasets = [{"id": 12, "columns": COLUMNS, "labelled_values": labelled}]
        planned = plan_query(_plan(filters=[place]), datasets, METRICS, [])
        assert planned.filters[0]["shown_value"] == "Ha Noi"
