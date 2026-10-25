from types import SimpleNamespace

import pytest

from text_to_bi.superset_semantic_layer.modules.agent_ladder.service import (
    DerivedColumnKeys,
    checked_dataset_proposal,
    checked_dataset_sql,
    checked_metric_draft,
    derived_column_keys,
    matching_metric,
    source_columns,
    source_metric,
    unique_metric_name,
)
from text_to_bi.superset_semantic_layer.modules.semantic_query.members import (
    MAX_CODED_VALUES,
    build_values_payload,
    coded_value_columns,
    coded_values_from_rows,
)


def _column(name, **fields):
    defaults = {
        "is_active": True, "expression": None, "type": "NUMERIC", "is_dttm": False, "groupby": True,
        "filterable": True, "verbose_name": None,
    }
    return SimpleNamespace(column_name=name, **{**defaults, **fields})


DAILY_WIND = "MAX(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' THEN toc_do_gio_toi_da_kmh END)"
DATASET = SimpleNamespace(
    id=12, sql=None,
    columns=[
        _column("loai_quan_sat", type="VARCHAR(30)"),
        _column("gio_giat_toi_da_kmh"),
        _column("ten_thanh_pho", expression="(SELECT ten FROM dim)"),
        _column("thanh_pho_key", type="BIGINT"),
        _column("cot_tat", is_active=False),
    ],
    metrics=[SimpleNamespace(id=23, metric_name="toc_do_gio_toi_da", expression=DAILY_WIND)],
)
DRAFT = {
    "metric_name": "Gio_giat_toi_da", "label": "Gió giật tối đa", "unit": "km/h",
    "expression": "MAX(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' THEN gio_giat_toi_da_kmh END)",
    "definition": "Tốc độ gió giật lớn nhất trong ngày.",
}


def test_a_contract_formula_on_live_columns_is_accepted_with_a_lowercase_name():
    draft = checked_metric_draft(DRAFT, DATASET)
    assert (draft.metric_name, draft.unit) == ("gio_giat_toi_da", "km/h")


@pytest.mark.parametrize("changes", [
    {"expression": "MAX(gio_giat_toi_da_kmh) / 2"},
    {"expression": "MAX(ten_thanh_pho)"},
    {"expression": "MAX(cot_tat)"},
    {"expression": "MAX((SELECT 1))"},
    {"metric_name": "gió giật"},
    {"definition": "  "},
    {"label": None},
])
def test_anything_beyond_a_contract_formula_is_refused(changes):
    with pytest.raises(ValueError):
        checked_metric_draft({**DRAFT, **changes}, DATASET)


def test_the_same_formula_written_differently_finds_the_saved_metric():
    rewritten = "max(case when loai_quan_sat='DU_BAO_NGAY' then toc_do_gio_toi_da_kmh end)"
    assert matching_metric(DATASET, rewritten).id == 23
    assert matching_metric(DATASET, DAILY_WIND.replace("DU_BAO_NGAY", "DU_BAO_GIO")) is None
    assert unique_metric_name(DATASET, "toc_do_gio_toi_da") == "toc_do_gio_toi_da_2"


def test_columns_are_explained_by_the_dictionary_and_name_their_foreign_key_target():
    entries = {
        "gio_giat_toi_da_kmh": SimpleNamespace(
            display_name="Gió giật tối đa", unit="km/h", business_term="Lớn nhất.", referenced_column=None,
        ),
        "thanh_pho_key": SimpleNamespace(
            display_name="Khóa thành phố", unit=None, business_term=None, referenced_column=147,
        ),
    }
    columns = source_columns(DATASET, entries, {147: (10, "thanh_pho_key")})

    assert [column["name"] for column in columns] == ["loai_quan_sat", "gio_giat_toi_da_kmh", "thanh_pho_key"]
    assert columns[1] == {
        "name": "gio_giat_toi_da_kmh", "label": "Gió giật tối đa", "type": "NUMERIC", "unit": "km/h",
        "description": "Lớn nhất.", "temporal": False, "groupby": True, "filterable": True,
    }
    assert columns[2]["references"] == {"dataset_id": 10, "column": "thanh_pho_key"}
    described = source_metric(DATASET.metrics[0], "approved", "manual", None)
    assert described["state"] == "approved" and "definition" not in described


LOADS = SimpleNamespace(id=14, table_name="tb_lan_nap_du_lieu", schema="public", database_id=1)
CITIES = SimpleNamespace(id=10, table_name="dm_thanh_pho", schema="public", database_id=1)
BASE_DATASETS = {"tb_lan_nap_du_lieu": LOADS, "dm_thanh_pho": CITIES}
LOAD_SQL = (
    "SELECT lan_nap_id, CAST(bat_dau_luc AS DATE) AS ngay, trang_thai, "
    "CASE WHEN trang_thai = 'LOI' THEN 1 ELSE 0 END AS la_loi FROM public.tb_lan_nap_du_lieu"
)


def test_a_select_over_base_datasets_names_its_columns_and_sources():
    checked = checked_dataset_sql(LOAD_SQL, BASE_DATASETS)
    assert checked.output_columns == ["lan_nap_id", "ngay", "trang_thai", "la_loi"]
    assert [dataset.id for dataset in checked.source_datasets] == [14]


@pytest.mark.parametrize("sql", [
    "DELETE FROM tb_lan_nap_du_lieu",
    "SELECT lan_nap_id FROM tb_lan_nap_du_lieu; DROP TABLE dm_thanh_pho",
    "SELECT * FROM tb_lan_nap_du_lieu",
    "SELECT lan_nap_id FROM ab_user",
    "SELECT lan_nap_id FROM private.tb_lan_nap_du_lieu",
    "SELECT pg_read_file('/etc/passwd') AS noi_dung FROM tb_lan_nap_du_lieu",
    "SELECT lan_nap_id, COUNT(*) FROM tb_lan_nap_du_lieu GROUP BY lan_nap_id",
    "SELECT lan_nap_id INTO bang_moi FROM tb_lan_nap_du_lieu",
    "SELECT a.lan_nap_id FROM tb_lan_nap_du_lieu a JOIN (SELECT id FROM ab_user) u ON u.id = a.lan_nap_id",
])
def test_anything_but_a_read_of_allowed_base_datasets_with_named_columns_is_refused(sql):
    with pytest.raises(ValueError):
        checked_dataset_sql(sql, BASE_DATASETS)


def test_a_proposal_checks_its_metric_against_the_columns_the_sql_returns():
    body = {
        "name": "Lan_nap_theo_ngay", "label": "Lần nạp dữ liệu theo ngày", "sql": LOAD_SQL,
        "metric": {"metric_name": "so_lan_nap_loi", "label": "Số lần nạp lỗi", "expression": "SUM(la_loi)",
                   "definition": "Số lần nạp kết thúc với trạng thái lỗi.", "unit": "lần"},
        "question": "Tuần trước có bao nhiêu lần nạp lỗi?",
    }
    proposal = checked_dataset_proposal(body, BASE_DATASETS)
    assert (proposal["name"], proposal["database_id"], proposal["schema"]) == ("lan_nap_theo_ngay", 1, "public")
    assert proposal["source_dataset_ids"] == [14] and proposal["metric"]["expression"] == "SUM(la_loi)"

    with pytest.raises(ValueError):
        checked_dataset_proposal({**body, "metric": {**body["metric"], "expression": "SUM(so_loi)"}}, BASE_DATASETS)


def test_a_code_column_lists_its_stored_values_so_a_formula_spells_them_exactly():
    loads = SimpleNamespace(id=14, columns=[
        _column("lan_nap_id", type="VARCHAR(36)"),
        _column("trang_thai", type="VARCHAR(20)"),
        _column("so_dong", type="INTEGER"),
        _column("ghi_chu", type="TEXT", expression="lower(ghi_chu)"),
    ])
    assert coded_value_columns(loads, {"lan_nap_id": SimpleNamespace(is_pk=True)}) == ["trang_thai"]
    assert [query["columns"] for query in build_values_payload(loads, ["trang_thai"])["queries"]] == [["trang_thai"]]
    rows = [{"trang_thai": "THAT_BAI"}, {"trang_thai": "THANH_CONG"}, {"trang_thai": None}]
    assert coded_values_from_rows(rows, "trang_thai") == ["THANH_CONG", "THAT_BAI"]
    assert coded_values_from_rows([{"ghi_chu": str(index)} for index in range(MAX_CODED_VALUES + 1)], "ghi_chu") is None
    assert coded_values_from_rows([{"loi": "503 Server Error: Service Unavailable for url: " + "x" * 40}], "loi") is None

    columns = source_columns(loads, {}, {}, {"trang_thai": ["THANH_CONG", "THAT_BAI"]})
    assert next(column for column in columns if column["name"] == "trang_thai")["values"] == ["THANH_CONG", "THAT_BAI"]
    assert "values" not in next(column for column in columns if column["name"] == "so_dong")


def _entry(**flags):
    return SimpleNamespace(**{"is_pk": False, "is_fk": False, "is_unique": False, **flags})


OBSERVATIONS = SimpleNamespace(id=7, table_name="tb_quan_sat_thoi_tiet")
CITIES = SimpleNamespace(id=6, table_name="dm_thanh_pho")
KEY_ENTRIES = {
    7: {"quan_sat_id": _entry(is_pk=True), "thanh_pho_id": _entry(is_fk=True), "loai_quan_sat": _entry()},
    6: {"thanh_pho_id": _entry(is_pk=True), "ma_thanh_pho": _entry(is_unique=True), "ten_thanh_pho": _entry()},
}


def test_a_proposed_dataset_keeps_the_keys_of_the_base_columns_it_reads_and_references_them():
    sql = """SELECT o.quan_sat_id, o.thanh_pho_id AS thanh_pho_key, c.ma_thanh_pho, o.loai_quan_sat,
      CAST(o.quan_sat_id AS TEXT) AS ma_chu
    FROM tb_quan_sat_thoi_tiet o JOIN dm_thanh_pho c ON c.thanh_pho_id = o.thanh_pho_id"""
    keys = derived_column_keys(sql, [OBSERVATIONS, CITIES], KEY_ENTRIES)
    assert keys["quan_sat_id"] == DerivedColumnKeys(is_pk=True, is_unique=False, referenced=(7, "quan_sat_id"))
    assert keys["thanh_pho_key"] == DerivedColumnKeys(is_pk=False, is_unique=False, referenced=(7, "thanh_pho_id"))
    # A joined table's unique column repeats once per observation, so it is only a reference here.
    assert keys["ma_thanh_pho"] == DerivedColumnKeys(is_pk=False, is_unique=False, referenced=(6, "ma_thanh_pho"))
    assert "loai_quan_sat" not in keys and "ma_chu" not in keys


@pytest.mark.parametrize("sql", [
    "SELECT quan_sat_id FROM tb_quan_sat_thoi_tiet GROUP BY quan_sat_id",
    "SELECT DISTINCT quan_sat_id FROM tb_quan_sat_thoi_tiet",
    "SELECT o.quan_sat_id FROM tb_quan_sat_thoi_tiet o JOIN dm_thanh_pho c ON c.ten_thanh_pho = o.loai_quan_sat",
])
def test_a_query_that_can_repeat_or_merge_rows_keeps_the_reference_but_not_the_primary_key(sql):
    keys = derived_column_keys(sql, [OBSERVATIONS, CITIES], KEY_ENTRIES)
    assert keys["quan_sat_id"] == DerivedColumnKeys(is_pk=False, is_unique=False, referenced=(7, "quan_sat_id"))
