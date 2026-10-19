"""Nap Open-Meteo vao lop tb_ nghiep vu va lam moi bang dashboard."""

from __future__ import annotations

import logging
import os
from datetime import datetime, time, timedelta
from typing import Any

import pendulum
import psycopg2
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from psycopg2.extras import execute_values


LOGGER = logging.getLogger(__name__)
API_URL = os.getenv("WEATHER_API_URL", "https://api.open-meteo.com/v1/forecast")
TIMEZONE = "Asia/Bangkok"

CURRENT_FIELDS = {
    "nhiet_do_c": "temperature_2m",
    "cam_nhan_c": "apparent_temperature",
    "do_am_pct": "relative_humidity_2m",
    "luong_mua_mm": "precipitation",
    "ap_suat_hpa": "pressure_msl",
    "may_phu_pct": "cloud_cover",
    "toc_do_gio_kmh": "wind_speed_10m",
    "gio_giat_kmh": "wind_gusts_10m",
    "tam_nhin_m": "visibility",
    "la_ban_ngay": "is_day",
}
HOURLY_FIELDS = {
    **CURRENT_FIELDS,
    "xac_suat_mua_pct": "precipitation_probability",
    "mua_mm": "rain",
}
DAILY_FIELDS = {
    "nhiet_do_thap_nhat_c": "temperature_2m_min",
    "nhiet_do_cao_nhat_c": "temperature_2m_max",
    "cam_nhan_thap_nhat_c": "apparent_temperature_min",
    "cam_nhan_cao_nhat_c": "apparent_temperature_max",
    "tong_luong_mua_mm": "precipitation_sum",
    "tong_mua_mm": "rain_sum",
    "tong_mua_rao_mm": "showers_sum",
    "tuyet_roi_cm": "snowfall_sum",
    "so_gio_co_mua": "precipitation_hours",
    "toc_do_gio_toi_da_kmh": "wind_speed_10m_max",
    "gio_giat_toi_da_kmh": "wind_gusts_10m_max",
    "thoi_luong_nang_gio": "sunshine_duration",
    "thoi_luong_ban_ngay_gio": "daylight_duration",
}


def database_dsn() -> str:
    return "host={host} port={port} dbname={name} user={user} password={password}".format(
        host=os.getenv("WAREHOUSE_DB_HOST", "warehouse-db"),
        port=os.getenv("WAREHOUSE_DB_PORT", "5432"),
        name=os.getenv("WAREHOUSE_DB_NAME", "data_wh"),
        user=os.getenv("WAREHOUSE_DB_USER", "bi"),
        password=os.getenv("WAREHOUSE_DB_PASSWORD", "bi_dev_password"),
    )


def as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def as_int(value: Any) -> int | None:
    return None if value is None else int(value)


def parse_timestamp(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def value_at(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None


def fetch_weather(city: dict[str, Any]) -> dict[str, Any]:
    params = {
        "latitude": city["vi_do"],
        "longitude": city["kinh_do"],
        "timezone": TIMEZONE,
        "past_days": 7,
        "forecast_days": 7,
        "current": ",".join([*CURRENT_FIELDS.values(), "weather_code"]),
        "hourly": ",".join([*HOURLY_FIELDS.values(), "weather_code"]),
        "daily": ",".join([*DAILY_FIELDS.values(), "weather_code", "sunrise", "sunset"]),
    }
    response = requests.get(API_URL, params=params, timeout=45)
    response.raise_for_status()
    return response.json()


def save_observation(
    cursor: Any,
    thanh_pho_id: int,
    nguon_du_lieu_id: int,
    dieu_kien_id: int | None,
    loai_quan_sat: str,
    thoi_diem: datetime,
    values: list[tuple[str, Any]],
    chi_so_ids: dict[str, int],
) -> int:
    cursor.execute(
        """
        INSERT INTO tb_quan_sat_thoi_tiet (
            thanh_pho_id, nguon_du_lieu_id, dieu_kien_id,
            loai_quan_sat, thoi_diem_quan_sat, ngay_id
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (thanh_pho_id, loai_quan_sat, thoi_diem_quan_sat) DO UPDATE SET
            nguon_du_lieu_id = EXCLUDED.nguon_du_lieu_id,
            dieu_kien_id = EXCLUDED.dieu_kien_id,
            ngay_id = EXCLUDED.ngay_id,
            lay_luc = now()
        RETURNING quan_sat_id
        """,
        (thanh_pho_id, nguon_du_lieu_id, dieu_kien_id, loai_quan_sat, thoi_diem, thoi_diem.date()),
    )
    quan_sat_id = cursor.fetchone()[0]
    cursor.execute("DELETE FROM tb_gia_tri_quan_sat WHERE quan_sat_id = %s", (quan_sat_id,))

    rows = []
    for ma_chi_so, value in values:
        if value is None:
            continue
        chi_so_id = chi_so_ids[ma_chi_so]
        if isinstance(value, bool):
            rows.append((quan_sat_id, chi_so_id, None, value, None))
        else:
            rows.append((quan_sat_id, chi_so_id, as_float(value), None, None))
    if rows:
        execute_values(
            cursor,
            """
            INSERT INTO tb_gia_tri_quan_sat (
                quan_sat_id, chi_so_id, gia_tri_so, gia_tri_dung_sai, gia_tri_chu
            ) VALUES %s
            ON CONFLICT (quan_sat_id, chi_so_id) DO UPDATE SET
                gia_tri_so = EXCLUDED.gia_tri_so,
                gia_tri_dung_sai = EXCLUDED.gia_tri_dung_sai,
                gia_tri_chu = EXCLUDED.gia_tri_chu
            """,
            rows,
        )
    return len(rows)


def api_values(payload: dict[str, Any], group: str, fields: dict[str, str], index: int | None = None):
    source = payload.get(group, {})
    result = []
    for ma_chi_so, api_name in fields.items():
        value = source.get(api_name)
        if index is not None:
            value = value_at(value or [], index)
        if ma_chi_so.endswith("_gio") and api_name in {"sunshine_duration", "daylight_duration"}:
            value = as_float(value) / 3600 if value is not None else None
        if ma_chi_so == "la_ban_ngay" and value is not None:
            value = bool(value)
        result.append((ma_chi_so, value))
    return result


def load_weather_warehouse() -> None:
    connection = psycopg2.connect(database_dsn())
    connection.autocommit = False
    lan_nap_id = None
    so_quan_sat = so_gia_tri = 0
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tb_lan_nap_du_lieu (trang_thai, so_thanh_pho)
                SELECT 'DANG_CHAY', COUNT(*) FROM dm_thanh_pho WHERE hoat_dong
                RETURNING lan_nap_id
                """
            )
            lan_nap_id = cursor.fetchone()[0]
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute("SELECT nguon_du_lieu_id FROM dm_nguon_du_lieu WHERE ma_nguon = 'OPEN_METEO'")
            nguon_du_lieu_id = cursor.fetchone()[0]
            cursor.execute("SELECT ma_chi_so, chi_so_id FROM dm_chi_so_thoi_tiet WHERE hoat_dong")
            chi_so_ids = dict(cursor.fetchall())
            cursor.execute("SELECT ma_thoi_tiet, dieu_kien_id FROM dm_dieu_kien_thoi_tiet")
            dieu_kien_ids = dict(cursor.fetchall())
            cursor.execute(
                """
                SELECT thanh_pho_id, ten_thanh_pho, vi_do::float, kinh_do::float
                FROM dm_thanh_pho WHERE hoat_dong ORDER BY thanh_pho_id
                """
            )
            cities = [
                {"thanh_pho_id": r[0], "ten_thanh_pho": r[1], "vi_do": r[2], "kinh_do": r[3]}
                for r in cursor.fetchall()
            ]

            for city in cities:
                LOGGER.info("Nap du lieu cho %s", city["ten_thanh_pho"])
                payload = fetch_weather(city)
                current = payload.get("current", {})
                current_time = parse_timestamp(current.get("time"))
                if current_time:
                    so_gia_tri += save_observation(
                        cursor, city["thanh_pho_id"], nguon_du_lieu_id,
                        dieu_kien_ids.get(as_int(current.get("weather_code"))),
                        "HIEN_TAI", current_time,
                        api_values(payload, "current", CURRENT_FIELDS), chi_so_ids,
                    )
                    so_quan_sat += 1

                hourly = payload.get("hourly", {})
                for index, timestamp in enumerate(hourly.get("time", [])):
                    thoi_diem = parse_timestamp(timestamp)
                    if thoi_diem is None:
                        continue
                    so_gia_tri += save_observation(
                        cursor, city["thanh_pho_id"], nguon_du_lieu_id,
                        dieu_kien_ids.get(as_int(value_at(hourly.get("weather_code", []), index))),
                        "DU_BAO_GIO", thoi_diem,
                        api_values(payload, "hourly", HOURLY_FIELDS, index), chi_so_ids,
                    )
                    so_quan_sat += 1

                daily = payload.get("daily", {})
                for index, date_value in enumerate(daily.get("time", [])):
                    ngay = datetime.fromisoformat(date_value).date()
                    so_gia_tri += save_observation(
                        cursor, city["thanh_pho_id"], nguon_du_lieu_id,
                        dieu_kien_ids.get(as_int(value_at(daily.get("weather_code", []), index))),
                        "DU_BAO_NGAY", datetime.combine(ngay, time.min),
                        api_values(payload, "daily", DAILY_FIELDS, index), chi_so_ids,
                    )
                    so_quan_sat += 1

            cursor.execute("SELECT lam_moi_du_lieu_dashboard()")
            connection.commit()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE tb_lan_nap_du_lieu
                    SET ket_thuc_luc = now(), trang_thai = 'THANH_CONG',
                        so_quan_sat = %s, so_gia_tri = %s
                    WHERE lan_nap_id = %s
                    """,
                    (so_quan_sat, so_gia_tri, lan_nap_id),
                )
            connection.commit()
        LOGGER.info("Da nap %s quan sat va %s gia tri", so_quan_sat, so_gia_tri)
    except Exception as exc:
        connection.rollback()
        if lan_nap_id is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE tb_lan_nap_du_lieu
                    SET ket_thuc_luc = now(), trang_thai = 'THAT_BAI', loi = %s
                    WHERE lan_nap_id = %s
                    """,
                    (str(exc)[:4000], lan_nap_id),
                )
            connection.commit()
        raise
    finally:
        connection.close()


with DAG(
    dag_id="weather_warehouse_ingest",
    description="Nap Open-Meteo vao bang tb_ va lam moi du lieu dashboard",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    schedule="0 * * * *",
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=20),
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["warehouse", "dm", "tb", "open-meteo"],
) as dag:
    PythonOperator(
        task_id="nap_tb_va_lam_moi_dashboard",
        python_callable=load_weather_warehouse,
    )
