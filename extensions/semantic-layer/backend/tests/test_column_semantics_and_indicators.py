import json
from types import SimpleNamespace

import pytest

from text_to_bi.superset_semantic_layer.modules.data_dictionary.column_semantics import (
    checked_column_semantics,
    default_semantic_role,
    json_list,
)
from text_to_bi.superset_semantic_layer.modules.data_dictionary.indicators import (
    MAX_INDICATORS,
    build_indicators_payload,
    checked_indicator_model,
    indicators_from_rows,
    stored_indicator_model,
)

VALUE_COLUMNS = {"quan_sat_id", "chi_so_id", "gia_tri_so", "gia_tri_dung_sai", "gia_tri_chu"}
CATALOG_COLUMNS = {"chi_so_id", "ma_chi_so", "ten_chi_so", "ten_don_vi", "kieu_du_lieu", "cach_tong_hop"}
CATALOG = {
    "kind": "catalog", "key_column": "chi_so_id", "code_column": "ma_chi_so", "name_column": "ten_chi_so",
    "unit_column": "ten_don_vi", "value_kind_column": "kieu_du_lieu", "aggregation_column": "cach_tong_hop",
    "aggregation_map": {"TRUNG_BINH": "AVG", "TONG": "SUM", "CUOI_CUNG": "NONE"},
}


@pytest.mark.parametrize(
    ("data_type", "temporal_kind", "is_key", "is_row_kind", "expected"),
    [
        ("BIGINT", None, True, False, "key"),
        ("VARCHAR(30)", None, False, True, "row_kind"),
        ("TIMESTAMP WITHOUT TIME ZONE", "timestamp", False, False, "time"),
        ("NUMERIC(12, 4)", None, False, False, "measure"),
        ("VARCHAR(100)", None, False, False, "dimension"),
    ],
)
def test_a_column_takes_a_role_from_its_keys_time_and_type(data_type, temporal_kind, is_key, is_row_kind, expected):
    assert default_semantic_role(data_type, temporal_kind, is_key, is_row_kind) == expected


def test_semantic_fields_are_stored_as_json_and_blank_text_as_null():
    values = checked_column_semantics(
        {"semantic_role": "measure", "aggregations": ["MAX", "AVG", "AVG"], "synonyms": [" nhiệt độ ", "", "nhiệt độ"],
         "description": "  "},
        0, "measure",
    )

    assert values == {"semantic_role": "measure", "aggregations": '["AVG", "MAX"]', "synonyms": '["nhiệt độ"]',
                      "description": None}
    assert json_list(values["aggregations"]) == ["AVG", "MAX"] and json_list("oops") == []
    assert checked_column_semantics({"aggregations": [], "synonyms": []}, 0, None) == {"aggregations": None, "synonyms": None}


@pytest.mark.parametrize(
    ("item", "role"),
    [
        ({"semantic_role": "metric"}, None),
        ({"aggregations": ["MEDIAN"]}, "measure"),
        ({"aggregations": ["SUM"]}, "dimension"),
        ({"synonyms": "nhiệt độ"}, None),
        ({"synonyms": ["x" * 101]}, None),
        ({"description": 3}, None),
    ],
)
def test_semantic_fields_that_do_not_fit_are_refused(item, role):
    with pytest.raises(ValueError):
        checked_column_semantics(item, 0, role)


def test_aggregations_are_kept_when_the_stored_role_is_checked_by_the_caller():
    assert checked_column_semantics({"aggregations": ["SUM"]}, 0, None) == {"aggregations": '["SUM"]'}


def test_a_values_table_and_a_catalog_are_declared_against_their_columns():
    values = checked_indicator_model(
        {"kind": "values", "indicator_column": "chi_so_id", "value_columns": {"SO": "gia_tri_so", "CHU": "gia_tri_chu"}},
        VALUE_COLUMNS,
    )

    assert values == {"kind": "values", "indicator_column": "chi_so_id",
                      "value_columns": {"SO": "gia_tri_so", "CHU": "gia_tri_chu"}}
    assert checked_indicator_model(CATALOG, CATALOG_COLUMNS) == CATALOG
    assert checked_indicator_model(None, VALUE_COLUMNS) is None
    assert stored_indicator_model(json.dumps(CATALOG)) == CATALOG and stored_indicator_model("{}") is None


@pytest.mark.parametrize(
    "model",
    [
        {"kind": "eav"},
        {"kind": "values", "indicator_column": "chi_so_id", "value_columns": {}},
        {"kind": "values", "indicator_column": "chi_so_id", "value_columns": {"SO": "khong_co"}},
        {"kind": "values", "indicator_column": "gia_tri_so", "value_columns": {"SO": "gia_tri_so"}},
        {"kind": "values", "value_columns": {"SO": "gia_tri_so"}},
        {**CATALOG, "name_column": None},
        {**CATALOG, "aggregation_map": {"TRUNG_BINH": "MEDIAN"}},
        {**CATALOG, "aggregation_column": None},
        {**CATALOG, "sql": "1"},
    ],
)
def test_indicator_declarations_that_do_not_fit_are_refused(model):
    columns = VALUE_COLUMNS if model.get("kind") == "values" else CATALOG_COLUMNS
    with pytest.raises(ValueError):
        checked_indicator_model(model, columns)


def test_the_indicator_list_maps_aggregations_and_reports_codes_left_unmapped():
    rows = [
        {"chi_so_id": 2, "ma_chi_so": "luong_mua_mm", "ten_chi_so": "Luong mua", "ten_don_vi": "Milimet",
         "kieu_du_lieu": "SO", "cach_tong_hop": "TONG"},
        {"chi_so_id": 1, "ma_chi_so": "nhiet_do_c", "ten_chi_so": "Nhiet do", "ten_don_vi": "Do C",
         "kieu_du_lieu": "SO", "cach_tong_hop": "TRUNG_BINH"},
        {"chi_so_id": 3, "ma_chi_so": "la_ban_ngay", "ten_chi_so": "Ban ngay", "ten_don_vi": "Dung/Sai",
         "kieu_du_lieu": "DUNG_SAI", "cach_tong_hop": "BAT_KY"},
        {"chi_so_id": None, "ma_chi_so": "bo_qua"},
    ]

    result = indicators_from_rows(rows, CATALOG)

    assert [(item["code"], item["aggregation"]) for item in result["indicators"]] == [
        ("la_ban_ngay", None), ("luong_mua_mm", "SUM"), ("nhiet_do_c", "AVG"),
    ]
    assert result["unmapped_aggregation_codes"] == ["BAT_KY"] and result["value_kinds"] == ["DUNG_SAI", "SO"]
    assert result["too_many"] is False


def test_the_indicator_query_reads_only_declared_columns_with_a_bounded_row_limit():
    query = build_indicators_payload(SimpleNamespace(id=6), CATALOG)["queries"][0]

    assert query["columns"] == ["chi_so_id", "ma_chi_so", "ten_chi_so", "ten_don_vi", "kieu_du_lieu", "cach_tong_hop"]
    assert query["row_limit"] == MAX_INDICATORS + 1
    with pytest.raises(ValueError):
        build_indicators_payload(SimpleNamespace(id=6), {**CATALOG, "code_column": "ma chi so"})
