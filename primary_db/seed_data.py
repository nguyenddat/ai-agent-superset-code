import logging
import os
import time

import psycopg

from ingest_data import init_database, insert_weather_observations


DATABASE_URL = os.environ["DATABASE_URL"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def connect_with_retry() -> psycopg.Connection:
    for attempt in range(30):
        try:
            return psycopg.connect(DATABASE_URL)
        except psycopg.OperationalError:
            if attempt == 29:
                raise
            logging.info("Đang chờ primary-db sẵn sàng (%s/30).", attempt + 1)
            time.sleep(2)
    raise RuntimeError("Không thể kết nối primary-db")


if __name__ == "__main__":
    with connect_with_retry() as connection:
        init_database(connection)
        logging.info("Đã khởi tạo database.")

        try:
            count = insert_weather_observations(connection)
            logging.info("Đã nạp %s quan sát thời tiết realtime.", count)
        except Exception:
            connection.rollback()
            logging.exception(
                "Không nạp được dữ liệu realtime ban đầu; ingest sẽ thử lại khi chạy."
            )
