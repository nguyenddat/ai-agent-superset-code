from datetime import datetime
from types import SimpleNamespace

import pytest

from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.time_semantics import (
    MAX_ROW_KINDS,
    build_grain_profile_payload,
    checked_time_semantics,
    default_temporal_kind,
    grain_profile_from_rows,
)

TEMPORAL_KINDS = {"thoi_diem_quan_sat": "timestamp", "ngay_key": "date", "loai_quan_sat": None, "nhiet_do_c": None}
WEATHER_GRAINS = [
    {"row_kind_value": "DU_BAO_GIO", "label": "Dự báo theo giờ", "grain": "hour"},
    {"row_kind_value": "DU_BAO_NGAY", "label": " ", "grain": "day"},
]


@pytest.mark.parametrize(
    ("data_type", "is_dttm", "expected"),
    [
        ("TIMESTAMP WITHOUT TIME ZONE", True, "timestamp"),
        ("DATETIME", False, "timestamp"),
        ("DATE", True, "date"),
        ("VARCHAR(32)", True, "timestamp"),
        ("NUMERIC(6,2)", False, None),
        (None, False, None),
    ],
)
def test_a_column_takes_its_temporal_kind_from_its_type(data_type, is_dttm, expected):
    assert default_temporal_kind(data_type, is_dttm) == expected


def test_grains_per_kind_of_row_are_kept_with_a_label_defaulting_to_the_value():
    checked = checked_time_semantics("thoi_diem_quan_sat", "loai_quan_sat", WEATHER_GRAINS, TEMPORAL_KINDS)

    assert checked == [
        {"row_kind_value": "DU_BAO_GIO", "label": "Dự báo theo giờ", "grain": "hour"},
        {"row_kind_value": "DU_BAO_NGAY", "label": "DU_BAO_NGAY", "grain": "day"},
    ]


def test_a_dataset_with_one_kind_of_row_has_one_grain_without_a_value():
    checked = checked_time_semantics("ngay_key", None, [{"row_kind_value": None, "grain": "day"}], TEMPORAL_KINDS)

    assert checked == [{"row_kind_value": None, "label": None, "grain": "day"}]
    assert checked_time_semantics(None, None, [], TEMPORAL_KINDS) == []


@pytest.mark.parametrize(
    ("time_column", "row_kind_column", "grains"),
    [
        ("nhiet_do_c", None, []),
        ("cot_khong_co", None, []),
        ("thoi_diem_quan_sat", "thoi_diem_quan_sat", []),
        (None, "loai_quan_sat", []),
        (None, None, [{"row_kind_value": None, "grain": "day"}]),
        ("thoi_diem_quan_sat", None, WEATHER_GRAINS),
        ("thoi_diem_quan_sat", None, [{"row_kind_value": "DU_BAO_GIO", "grain": "hour"}]),
        ("thoi_diem_quan_sat", "loai_quan_sat", [{"row_kind_value": None, "grain": "hour"}]),
        ("thoi_diem_quan_sat", "loai_quan_sat", [{"row_kind_value": "A", "grain": "minute"}]),
        ("thoi_diem_quan_sat", "loai_quan_sat", [{"row_kind_value": "A", "grain": "hour", "sql": "1"}]),
        ("thoi_diem_quan_sat", "loai_quan_sat", [WEATHER_GRAINS[0], WEATHER_GRAINS[0]]),
        ("thoi_diem_quan_sat", "loai_quan_sat", "hour"),
        (
            "thoi_diem_quan_sat", "loai_quan_sat",
            [{"row_kind_value": f"K{index}", "grain": "hour"} for index in range(MAX_ROW_KINDS + 1)],
        ),
    ],
)
def test_time_semantics_that_do_not_fit_the_columns_are_refused(time_column, row_kind_column, grains):
    with pytest.raises(ValueError):
        checked_time_semantics(time_column, row_kind_column, grains, TEMPORAL_KINDS)


def test_the_profile_query_groups_by_kind_of_row_with_a_bounded_row_limit():
    dataset = SimpleNamespace(id=12)

    query = build_grain_profile_payload(dataset, "thoi_diem_quan_sat", "loai_quan_sat", "timestamp")["queries"][0]

    assert query["columns"] == ["loai_quan_sat"]
    assert query["row_limit"] == MAX_ROW_KINDS + 1
    assert {metric["label"] for metric in query["metrics"]} == {
        "row_count", "first_moment", "last_moment", "moments", "days", "off_the_hour", "off_midnight", "off_first_day",
    }
    with pytest.raises(ValueError):
        build_grain_profile_payload(dataset, "ngay; DROP TABLE x", None, "date")


def test_a_date_column_is_profiled_without_extracting_a_time_of_day():
    query = build_grain_profile_payload(SimpleNamespace(id=12), "ngay_key", None, "date")["queries"][0]

    assert query["columns"] == []
    assert not any(
        "HOUR" in metric["sqlExpression"] or "MINUTE" in metric["sqlExpression"] for metric in query["metrics"]
    )


def test_the_profile_suggests_hours_days_months_and_irregular_moments():
    def row(value, off_the_hour=0, off_midnight=0, off_first_day=0, moments=24):
        return {
            "loai_quan_sat": value,
            "row_count": 100,
            "first_moment": datetime(2026, 10, 15),
            "last_moment": "2026-11-01T23:00:00",
            "moments": moments,
            "days": 18,
            "off_the_hour": off_the_hour,
            "off_midnight": off_midnight,
            "off_first_day": off_first_day,
        }

    rows = [
        row("HIEN_TAI", off_the_hour=40, off_midnight=90, off_first_day=80),
        row("DU_BAO_GIO", off_midnight=96, off_first_day=90),
        row("DU_BAO_NGAY", off_first_day=12, moments=18),
        row("THANG", moments=3),
        row(None),
    ]

    profiles, too_many = grain_profile_from_rows(rows, "loai_quan_sat")

    assert [(item["row_kind_value"], item["suggested_grain"]) for item in profiles] == [
        ("DU_BAO_GIO", "hour"),
        ("DU_BAO_NGAY", "day"),
        ("HIEN_TAI", "instant"),
        ("THANG", "month"),
    ]
    assert profiles[0]["first_moment"] == "2026-10-15T00:00:00" and too_many is False


def test_a_column_with_more_kinds_than_a_grain_list_keeps_is_flagged():
    rows = [{"loai": f"K{index}", "row_count": 1} for index in range(MAX_ROW_KINDS + 1)]

    profiles, too_many = grain_profile_from_rows(rows, "loai")

    assert len(profiles) == MAX_ROW_KINDS and too_many is True
