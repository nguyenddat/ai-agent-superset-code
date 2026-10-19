"""Register saved Superset metrics and calculated columns on the warehouse fact datasets."""

from __future__ import annotations

import json
import logging
import os

from superset.app import create_app


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOGGER = logging.getLogger(__name__)

MANAGED_MARKER = json.dumps({"managed_by": "metrics_bootstrap"})

# fact_tong_hop_thoi_tiet mixes three grains in one table, so each metric selects its own rows:
# HIEN_TAI (current), DU_BAO_GIO (hourly forecast) and DU_BAO_NGAY (daily forecast).
HOURLY = "loai_quan_sat = 'DU_BAO_GIO'"
DAILY = "loai_quan_sat = 'DU_BAO_NGAY'"


def _city_lookup(table_name: str, column_name: str) -> str:
    # Superset queries a physical dataset without an alias, so the subquery can correlate on the table name.
    return (
        f"(SELECT d.{column_name} FROM public.dim_thanh_pho d"
        f" WHERE d.thanh_pho_key = {table_name}.thanh_pho_key)"
    )


METRICS: dict[str, dict[str, object]] = {
    "fact_tong_hop_thoi_tiet": {
        "main_dttm_col": "thoi_diem_quan_sat",
        "calculated_columns": [
            {
                "column_name": "ten_thanh_pho",
                "verbose_name": "Tên thành phố",
                "expression": _city_lookup("fact_tong_hop_thoi_tiet", "ten_thanh_pho"),
                "type": "VARCHAR",
                "description": "Tên thành phố, tra từ dim_thanh_pho theo thanh_pho_key.",
            },
            {
                "column_name": "vung",
                "verbose_name": "Vùng",
                "expression": _city_lookup("fact_tong_hop_thoi_tiet", "vung"),
                "type": "VARCHAR",
                "description": "Vùng địa lý của thành phố, tra từ dim_thanh_pho theo thanh_pho_key.",
            },
        ],
        "metrics": [
            {
                "metric_name": "nhiet_do_trung_binh",
                "verbose_name": "Nhiệt độ trung bình",
                "expression": f"AVG(CASE WHEN {HOURLY} THEN nhiet_do_c END)",
                "description": "Nhiệt độ không khí trung bình (°C), tính trên các bản ghi dự báo theo giờ.",
                "d3format": ",.1f",
            },
            {
                "metric_name": "nhiet_do_cao_nhat",
                "verbose_name": "Nhiệt độ cao nhất",
                "expression": f"MAX(CASE WHEN {DAILY} THEN nhiet_do_cao_nhat_c END)",
                "description": "Nhiệt độ cao nhất (°C) trong phạm vi lọc, lấy từ nhiệt độ cao nhất của từng ngày.",
                "d3format": ",.1f",
            },
            {
                "metric_name": "nhiet_do_thap_nhat",
                "verbose_name": "Nhiệt độ thấp nhất",
                "expression": f"MIN(CASE WHEN {DAILY} THEN nhiet_do_thap_nhat_c END)",
                "description": "Nhiệt độ thấp nhất (°C) trong phạm vi lọc, lấy từ nhiệt độ thấp nhất của từng ngày.",
                "d3format": ",.1f",
            },
            {
                "metric_name": "do_am_trung_binh",
                "verbose_name": "Độ ẩm trung bình",
                "expression": f"AVG(CASE WHEN {HOURLY} THEN do_am_pct END)",
                "description": "Độ ẩm tương đối trung bình (%), tính trên các bản ghi dự báo theo giờ.",
                "d3format": ",.1f",
            },
            {
                "metric_name": "tong_luong_mua",
                "verbose_name": "Tổng lượng mưa",
                "expression": f"SUM(CASE WHEN {DAILY} THEN tong_luong_mua_mm END)",
                "description": (
                    "Tổng lượng mưa (mm), cộng từ tổng lượng mưa của từng ngày. "
                    "Khi không group theo thành phố, kết quả là tổng của mọi thành phố trong phạm vi lọc."
                ),
                "d3format": ",.1f",
            },
            {
                "metric_name": "so_ngay_co_mua",
                "verbose_name": "Số ngày có mưa",
                "expression": f"COUNT(CASE WHEN {DAILY} AND tong_luong_mua_mm > 0 THEN 1 END)",
                "description": (
                    "Số ngày có lượng mưa lớn hơn 0 mm. "
                    "Mỗi cặp thành phố và ngày được đếm một lần."
                ),
                "d3format": ",d",
            },
            {
                "metric_name": "ty_le_ngay_co_mua",
                "verbose_name": "Tỷ lệ ngày có mưa",
                "expression": (
                    f"100.0 * COUNT(CASE WHEN {DAILY} AND tong_luong_mua_mm > 0 THEN 1 END)"
                    f" / NULLIF(COUNT(CASE WHEN {DAILY} THEN 1 END), 0)"
                ),
                "description": "Phần trăm số ngày có mưa trên tổng số ngày (thành phố × ngày) trong phạm vi lọc.",
                "d3format": ",.1f",
            },
            {
                "metric_name": "toc_do_gio_toi_da",
                "verbose_name": "Tốc độ gió tối đa",
                "expression": f"MAX(CASE WHEN {DAILY} THEN toc_do_gio_toi_da_kmh END)",
                "description": "Tốc độ gió tối đa (km/h) trong phạm vi lọc, lấy từ tốc độ gió tối đa của từng ngày.",
                "d3format": ",.1f",
            },
        ],
    },
}


def bootstrap() -> None:
    app = create_app()
    with app.app_context():
        from superset import db
        from superset.connectors.sqla.models import SqlaTable, SqlMetric, TableColumn
        from superset.models.core import Database

        database_name = os.getenv("WAREHOUSE_SUPERSET_NAME", "Weather Warehouse")
        database = (
            db.session.query(Database)
            .filter(Database.database_name == database_name)
            .one_or_none()
        )
        if database is None:
            raise RuntimeError(f"Superset database '{database_name}' not found; run bootstrap_warehouse.py first.")

        for table_name, spec in METRICS.items():
            dataset = (
                db.session.query(SqlaTable)
                .filter(
                    SqlaTable.database_id == database.id,
                    SqlaTable.schema == "public",
                    SqlaTable.table_name == table_name,
                )
                .one_or_none()
            )
            if dataset is None:
                LOGGER.warning("Dataset %s not found; skipping its metrics.", table_name)
                continue

            dataset.main_dttm_col = spec["main_dttm_col"]

            columns = {column.column_name: column for column in dataset.columns}
            for values in spec.get("calculated_columns", []):
                column = columns.get(values["column_name"])
                if column is None:
                    column = TableColumn(table=dataset, column_name=values["column_name"])
                    dataset.columns.append(column)
                for field, value in values.items():
                    setattr(column, field, value)
                column.groupby = True
                column.filterable = True

            existing = {metric.metric_name: metric for metric in dataset.metrics}
            created = updated = 0
            for values in spec["metrics"]:
                metric = existing.get(values["metric_name"])
                if metric is None:
                    metric = SqlMetric(table=dataset, metric_name=values["metric_name"])
                    dataset.metrics.append(metric)
                    created += 1
                else:
                    updated += 1
                for field, value in values.items():
                    setattr(metric, field, value)
                metric.extra = MANAGED_MARKER

            db.session.commit()
            LOGGER.info("Metrics ready on %s: created %s, updated %s", table_name, created, updated)


if __name__ == "__main__":
    bootstrap()
