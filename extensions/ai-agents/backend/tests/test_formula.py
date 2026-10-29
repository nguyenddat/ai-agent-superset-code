import pytest

from text_to_bi.superset_ai_agent.modules.chat.services.formula import answers_anything, doubtful_result, told_formula

COLUMNS = [
    {"name": "trang_thai", "label": "Trạng thái"},
    {"name": "lan_nap_id", "label": "Mã lần nạp"},
    {"name": "loai_quan_sat", "label": "Loại quan sát"},
    {"name": "nhiet_do"},
]


def _sentence(parts, by_column=False):
    return "".join(part["column" if by_column else "label"] if "column" in part else part["text"] for part in parts)


def test_a_filtered_count_reads_as_a_sentence_with_business_labels_or_column_names():
    parts = told_formula("COUNT(CASE WHEN trang_thai = 'THAT_BAI' THEN lan_nap_id END)", COLUMNS)
    assert _sentence(parts) == "Đếm số Mã lần nạp, chỉ tính các dòng có Trạng thái là “THAT_BAI”"
    assert _sentence(parts, by_column=True) == "Đếm số lan_nap_id, chỉ tính các dòng có trang_thai là “THAT_BAI”"


@pytest.mark.parametrize(("expression", "sentence"), [
    ("AVG(nhiet_do)", "Trung bình nhiet_do"),
    ("MAX(nhiet_do)", "Giá trị lớn nhất của nhiet_do"),
    (
        "COUNT(CASE WHEN nhiet_do >= 35 AND loai_quan_sat IN ('DU_BAO_NGAY', 'HIEN_TAI') THEN 1 END)",
        "Đếm số dòng có nhiet_do từ 35 trở lên và Loại quan sát thuộc “DU_BAO_NGAY”, “HIEN_TAI”",
    ),
    (
        "SUM(CASE WHEN nhiet_do < 0 OR trang_thai IS NULL THEN 1 END)",
        "Đếm số dòng có nhiet_do nhỏ hơn 0 hoặc Trạng thái trống",
    ),
    ("SUM(CASE WHEN nhiet_do <= 0 THEN nhiet_do END)", "Tổng nhiet_do, chỉ tính các dòng có nhiet_do không quá 0"),
])
def test_contract_formulas_read_in_plain_vietnamese(expression, sentence):
    assert _sentence(told_formula(expression, COLUMNS)) == sentence


@pytest.mark.parametrize("expression", ["MAX(nhiet_do) / 2", "SUM(cot_khac)", "MAX(t.nhiet_do)", "not sql ((("])
def test_a_formula_the_sentence_cannot_tell_faithfully_gives_none(expression):
    assert told_formula(expression, COLUMNS) is None


def _result(rows, **fields):
    return {
        "metrics": [{"name": "so_lan_nap_loi"}], "rows": rows, "row_count": len(rows), "total_rows": len(rows),
        "truncated": False, "coverage": {"status": "full"}, **fields,
    }


def test_a_provisional_figure_of_nothing_or_only_zeros_is_doubted_unless_the_period_has_no_data():
    assert doubtful_result(_result([])) == "empty"
    assert doubtful_result(_result([{"so_lan_nap_loi": 0}, {"so_lan_nap_loi": None}])) == "zero"
    assert doubtful_result(_result([{"so_lan_nap_loi": 2}])) is None
    assert doubtful_result(_result([], coverage={"status": "none"})) is None


def test_a_metric_that_gives_a_value_over_all_the_data_is_not_a_wrong_formula():
    assert answers_anything({"rows": [{"so_lan_nap_loi": "2.0000"}]}, "so_lan_nap_loi")
    assert not answers_anything({"rows": [{"so_lan_nap_loi": "0.0000"}, {"so_lan_nap_loi": None}]}, "so_lan_nap_loi")
    assert not answers_anything({"rows": []}, "so_lan_nap_loi")
