from __future__ import annotations

import json
import logging
import os
from typing import Any

from superset.app import create_app


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOGGER = logging.getLogger(__name__)

DATASET_NAME = "fact_tong_hop_thoi_tiet"
DASHBOARD_SLUG = "thoi-tiet-tong-quan"
DASHBOARD_TITLE = "Tổng quan thời tiết"
TIME_COLUMN = "thoi_diem_quan_sat"
NO_TIME_FILTER = [
    {
        "clause": "WHERE",
        "subject": TIME_COLUMN,
        "operator": "TEMPORAL_RANGE",
        "comparator": "No filter",
        "expressionType": "SIMPLE",
    }
]


def _big_number(metric: str) -> dict[str, Any]:
    return {
        "viz_type": "big_number_total",
        "metric": metric,
        "adhoc_filters": NO_TIME_FILTER,
        "header_font_size": 0.4,
        "subheader_font_size": 0.15,
        "y_axis_format": ",.1f",
    }


def _timeseries(viz_type: str, metric: str, time_grain: str) -> dict[str, Any]:
    return {
        "viz_type": viz_type,
        "x_axis": TIME_COLUMN,
        "time_grain_sqla": time_grain,
        "metrics": [metric],
        "groupby": [],
        "adhoc_filters": NO_TIME_FILTER,
        "row_limit": 10000,
        "show_legend": False,
        "rich_tooltip": True,
        "y_axis_format": ",.1f",
    }


# Each layout row sums to the 12-column dashboard grid width.
LAYOUT: list[list[tuple[str, int, dict[str, Any]]]] = [
    [
        ("Nhiệt độ trung bình (°C)", 3, _big_number("nhiet_do_trung_binh")),
        ("Nhiệt độ cao nhất (°C)", 3, _big_number("nhiet_do_cao_nhat")),
        ("Tổng lượng mưa (mm)", 3, _big_number("tong_luong_mua")),
        ("Tỷ lệ ngày có mưa (%)", 3, _big_number("ty_le_ngay_co_mua")),
    ],
    [
        ("Nhiệt độ trung bình theo giờ", 6, _timeseries("echarts_timeseries_line", "nhiet_do_trung_binh", "PT1H")),
        ("Tổng lượng mưa theo ngày", 6, _timeseries("echarts_timeseries_bar", "tong_luong_mua", "P1D")),
    ],
    [
        (
            "Tổng lượng mưa theo thành phố",
            6,
            {
                "viz_type": "echarts_timeseries_bar",
                "x_axis": "ten_thanh_pho",
                "metrics": ["tong_luong_mua"],
                "groupby": [],
                "adhoc_filters": NO_TIME_FILTER,
                "x_axis_sort": "tong_luong_mua",
                "x_axis_sort_asc": False,
                "row_limit": 100,
                "show_legend": False,
                "rich_tooltip": True,
                "y_axis_format": ",.1f",
            },
        ),
        (
            "Thời tiết theo thành phố",
            6,
            {
                "viz_type": "table",
                "query_mode": "aggregate",
                "groupby": ["ten_thanh_pho", "vung"],
                "metrics": ["nhiet_do_trung_binh", "nhiet_do_cao_nhat", "nhiet_do_thap_nhat", "ty_le_ngay_co_mua"],
                "adhoc_filters": NO_TIME_FILTER,
                "timeseries_limit_metric": "nhiet_do_trung_binh",
                "order_desc": True,
                "row_limit": 100,
            },
        ),
    ],
]


def _position_json(rows: list[list[tuple[Any, int]]]) -> dict[str, Any]:
    """Build a Superset v2 dashboard layout with one row per LAYOUT entry."""
    position: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": DASHBOARD_TITLE}},
    }
    for row_index, row in enumerate(rows, start=1):
        row_id = f"ROW-{row_index}"
        position["GRID_ID"]["children"].append(row_id)
        position[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for chart, width in row:
            chart_id = f"CHART-{chart.id}"
            position[row_id]["children"].append(chart_id)
            position[chart_id] = {
                "type": "CHART",
                "id": chart_id,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "width": width,
                    "height": 30 if row_index == 1 else 50,
                    "chartId": chart.id,
                    "sliceName": chart.slice_name,
                    "uuid": str(chart.uuid),
                },
            }
    return position


def bootstrap() -> None:
    app = create_app()
    with app.app_context():
        from superset import db, security_manager
        from superset.connectors.sqla.models import SqlaTable
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice

        database_name = os.getenv("WAREHOUSE_SUPERSET_NAME", "Weather Warehouse")
        dataset = (
            db.session.query(SqlaTable)
            .join(Database, SqlaTable.database_id == Database.id)
            .filter(
                Database.database_name == database_name,
                SqlaTable.schema == "public",
                SqlaTable.table_name == DATASET_NAME,
            )
            .one_or_none()
        )
        if dataset is None:
            raise RuntimeError(f"Dataset {DATASET_NAME} not found; run bootstrap_metrics.py first.")

        admin = security_manager.find_user(username=os.getenv("SUPERSET_ADMIN_USERNAME", "admin"))
        owners = [admin] if admin else []
        datasource = f"{dataset.id}__table"

        rows: list[list[tuple[Any, int]]] = []
        created = 0
        for layout_row in LAYOUT:
            row = []
            for name, width, form_data in layout_row:
                chart = (
                    db.session.query(Slice)
                    .filter(
                        Slice.slice_name == name,
                        Slice.datasource_type == "table",
                        Slice.datasource_id == dataset.id,
                    )
                    .one_or_none()
                )
                if chart is None:
                    chart = Slice(slice_name=name, datasource_type="table", datasource_id=dataset.id)
                    db.session.add(chart)
                    created += 1
                chart.viz_type = form_data["viz_type"]
                chart.datasource_name = dataset.table_name
                chart.params = json.dumps({**form_data, "datasource": datasource})
                chart.owners = owners
                row.append((chart, width))
            rows.append(row)
        db.session.flush()

        dashboard = db.session.query(Dashboard).filter(Dashboard.slug == DASHBOARD_SLUG).one_or_none()
        if dashboard is None:
            dashboard = Dashboard(slug=DASHBOARD_SLUG)
            db.session.add(dashboard)

        # Keep metadata written by other tools, such as Semantic Layer dataset IDs.
        metadata = json.loads(dashboard.json_metadata or "{}")
        metadata.setdefault("refresh_frequency", 0)
        metadata.setdefault("native_filter_configuration", [])
        metadata.setdefault("cross_filters_enabled", True)

        dashboard.dashboard_title = DASHBOARD_TITLE
        dashboard.published = True
        dashboard.owners = owners
        dashboard.slices = [chart for row in rows for chart, _ in row]
        dashboard.position_json = json.dumps(_position_json(rows))
        dashboard.json_metadata = json.dumps(metadata)
        db.session.commit()

        LOGGER.info(
            "Dashboard ready: /superset/dashboard/%s/ (charts created %s, total %s)",
            DASHBOARD_SLUG,
            created,
            len(dashboard.slices),
        )


if __name__ == "__main__":
    bootstrap()
