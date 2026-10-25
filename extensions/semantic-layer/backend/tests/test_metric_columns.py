from text_to_bi.superset_semantic_layer.modules.business_model.metric_columns import metric_columns

COLUMNS = ["loai_quan_sat", "nhiet_do_c", "tong_luong_mua_mm", "thanh_pho_id", "Nhiet Do"]


def roles(expression: str) -> dict[str, str] | None:
    result = metric_columns(expression, COLUMNS, "postgres")
    return None if result is None else {column["name"]: column["role"] for column in result}


def test_case_condition_is_a_filter_and_the_aggregated_value_a_measure():
    assert roles("AVG(CASE WHEN loai_quan_sat = 'DU_BAO_GIO' THEN nhiet_do_c END)") == {
        "loai_quan_sat": "filter",
        "nhiet_do_c": "measure",
    }


def test_count_of_a_condition_has_only_filters():
    expression = "COUNT(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0 THEN 1 END)"
    assert roles(expression) == {"loai_quan_sat": "filter", "tong_luong_mua_mm": "filter"}


def test_filter_clause_and_window_partition_are_filters():
    assert roles("SUM(tong_luong_mua_mm) FILTER (WHERE loai_quan_sat = 'X')") == {
        "loai_quan_sat": "filter",
        "tong_luong_mua_mm": "measure",
    }
    assert roles("SUM(nhiet_do_c) OVER (PARTITION BY thanh_pho_id ORDER BY loai_quan_sat)") == {
        "loai_quan_sat": "filter",
        "nhiet_do_c": "measure",
        "thanh_pho_id": "filter",
    }


def test_a_column_used_both_ways_is_a_measure():
    assert roles("SUM(CASE WHEN nhiet_do_c > 0 THEN nhiet_do_c END)") == {"nhiet_do_c": "measure"}


def test_unknown_names_are_dropped_and_names_match_ignoring_case():
    assert roles('SUM(NHIET_DO_C) + SUM(not_a_column) + AVG("Nhiet Do")') == {"nhiet_do_c": "measure", "Nhiet Do": "measure"}


def test_count_star_uses_no_column_and_templating_cannot_be_parsed():
    assert roles("COUNT(*)") == {}
    assert roles("SUM(nhiet_do_c) {% if filter_values('city') %}+ 0{% endif %}") is None
