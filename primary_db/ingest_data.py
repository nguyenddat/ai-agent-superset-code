import json
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

import psycopg


INTERVAL_SECONDS = 900
DATABASE_URL = os.getenv("DATABASE_URL")

CITIES = (
    ("HN", "Hà Nội", 21.0285, 105.8542),
    ("HP", "Hải Phòng", 20.8449, 106.6881),
    ("DN", "Đà Nẵng", 16.0544, 108.2022),
    ("HCM", "Hồ Chí Minh", 10.8231, 106.6297),
    ("CT", "Cần Thơ", 10.0452, 105.7469),
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def fetch_current_weather(latitude: float, longitude: float) -> tuple[float, float, float, datetime]:
    query = urlencode({
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "wind_speed_unit": "kmh",
        "timezone": "UTC",
    })

    with urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=10) as response:
        current = json.load(response)["current"]

    observed_at = datetime.fromisoformat(current["time"]).replace(tzinfo=timezone.utc)
    return (
        float(current["temperature_2m"]),
        float(current["relative_humidity_2m"]),
        float(current["wind_speed_10m"]),
        observed_at,
    )


def init_database(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dm_thanhpho (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                ma_thanhpho VARCHAR(10) NOT NULL UNIQUE,
                ten_thanhpho VARCHAR(100) NOT NULL UNIQUE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS thoitiet (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                thanhpho_id BIGINT NOT NULL REFERENCES dm_thanhpho(id),
                nhiet_do_c NUMERIC(5, 2) NOT NULL,
                do_am_phan_tram NUMERIC(5, 2) NOT NULL CHECK (do_am_phan_tram BETWEEN 0 AND 100),
                toc_do_gio_kmh NUMERIC(6, 2) NOT NULL,
                thoi_gian_ghi_nhan TIMESTAMPTZ NOT NULL
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_thoitiet_thanhpho_thoigian
            ON thoitiet (thanhpho_id, thoi_gian_ghi_nhan DESC)
        """)

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_thoitiet_city_timestamp
            ON thoitiet (thanhpho_id, thoi_gian_ghi_nhan)
        """)

        cursor.executemany("""
            INSERT INTO dm_thanhpho (ma_thanhpho, ten_thanhpho)
            VALUES (%s, %s)
            ON CONFLICT (ma_thanhpho) DO UPDATE
            SET ten_thanhpho = EXCLUDED.ten_thanhpho
        """, [(code, name) for code, name, _, _ in CITIES])

    connection.commit()


def insert_weather_observations(connection: psycopg.Connection) -> int:
    observations = []

    for city_code, city_name, latitude, longitude in CITIES:
        temperature, humidity, wind_speed, observed_at = fetch_current_weather(latitude, longitude)
        observations.append((temperature, humidity, wind_speed, observed_at, city_code))
        logging.info("%s: %.1f°C | %.0f%% | %.1f km/h", city_name, temperature, humidity, wind_speed)

    with connection.cursor() as cursor:
        cursor.executemany("""
            INSERT INTO thoitiet (
                thanhpho_id, nhiet_do_c, do_am_phan_tram,
                toc_do_gio_kmh, thoi_gian_ghi_nhan
            )
            SELECT id, %s, %s, %s, %s
            FROM dm_thanhpho
            WHERE ma_thanhpho = %s
            ON CONFLICT (thanhpho_id, thoi_gian_ghi_nhan) DO UPDATE
            SET nhiet_do_c = EXCLUDED.nhiet_do_c,
                do_am_phan_tram = EXCLUDED.do_am_phan_tram,
                toc_do_gio_kmh = EXCLUDED.toc_do_gio_kmh
        """, observations)

    connection.commit()
    return len(observations)


if __name__ == "__main__":
    with psycopg.connect(DATABASE_URL) as connection:
        init_database(connection)
        logging.info("Đã khởi tạo database.")

    with psycopg.connect(DATABASE_URL) as connection:
        logging.info("Bắt đầu thu thập thời tiết mỗi %s giây.", INTERVAL_SECONDS)

        while True:
            try:
                count = insert_weather_observations(connection)
                logging.info("Đã ghi %s quan sát thời tiết.", count)
            except Exception:
                connection.rollback()
                logging.exception("Không thể lấy hoặc ghi dữ liệu thời tiết.")

            time.sleep(INTERVAL_SECONDS)
