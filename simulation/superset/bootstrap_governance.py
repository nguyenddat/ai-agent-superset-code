from __future__ import annotations

import json
import logging
import os
from typing import Any

from superset.app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOGGER = logging.getLogger(__name__)

REPORTING_SCHEMA = "text_to_bi_reporting"
REPORTING_ROLE = "text_to_bi_reporting"
DATABASE_NAME = "Text to BI Governance"
DASHBOARD_SLUG = "ai-agent-tong-quan"
DASHBOARD_TITLE = "Tổng quan AI Agent"
REPORT_TIMEZONE = "Asia/Ho_Chi_Minh"
MANAGED_MARKER = json.dumps({"managed_by": "governance_bootstrap"})
STATUS_COLORS = {"Thành công": "#0ca30c", "Cần xác nhận": "#fab219", "Lỗi": "#d03b3b"}

# Mirrors the AI Agent's AgentQuestion and AgentQuestionHandling models, so the views exist before the first
# question is asked. The agent creates the same tables with `checkfirst`, so whichever runs first wins.
QUESTION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS public.text_to_bi_agent_question (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    dashboard_id INTEGER,
    question TEXT NOT NULL,
    rewritten_question TEXT,
    history_turns INTEGER NOT NULL,
    glossary_terms JSON NOT NULL,
    metrics JSON NOT NULL,
    expert_rules JSON NOT NULL,
    missing JSON NOT NULL,
    requires_expert_rule BOOLEAN,
    suggestions JSON,
    status VARCHAR(20) NOT NULL,
    answer TEXT,
    error TEXT,
    duration_ms INTEGER,
    session_id INTEGER,
    tool_calls JSON,
    clarifications JSON,
    clarification_state VARCHAR(20),
    retry_of INTEGER,
    query_result JSON,
    created_on TIMESTAMP WITH TIME ZONE NOT NULL
);
ALTER TABLE public.text_to_bi_agent_question ADD COLUMN IF NOT EXISTS requires_expert_rule BOOLEAN;
ALTER TABLE public.text_to_bi_agent_question ADD COLUMN IF NOT EXISTS suggestions JSON;
ALTER TABLE public.text_to_bi_agent_question ADD COLUMN IF NOT EXISTS session_id INTEGER;
ALTER TABLE public.text_to_bi_agent_question ADD COLUMN IF NOT EXISTS tool_calls JSON;
ALTER TABLE public.text_to_bi_agent_question ADD COLUMN IF NOT EXISTS clarifications JSON;
ALTER TABLE public.text_to_bi_agent_question ADD COLUMN IF NOT EXISTS clarification_state VARCHAR(20);
ALTER TABLE public.text_to_bi_agent_question ADD COLUMN IF NOT EXISTS retry_of INTEGER;
ALTER TABLE public.text_to_bi_agent_question ADD COLUMN IF NOT EXISTS query_result JSON;
CREATE INDEX IF NOT EXISTS ix_text_to_bi_agent_question_created_on ON public.text_to_bi_agent_question (created_on);
CREATE INDEX IF NOT EXISTS ix_text_to_bi_agent_question_status ON public.text_to_bi_agent_question (status);
CREATE INDEX IF NOT EXISTS ix_text_to_bi_agent_question_user_id ON public.text_to_bi_agent_question (user_id);
CREATE TABLE IF NOT EXISTS public.text_to_bi_agent_question_handling (
    question_id INTEGER PRIMARY KEY REFERENCES public.text_to_bi_agent_question (id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL,
    note TEXT,
    handled_by INTEGER,
    handled_on TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_text_to_bi_agent_question_handling_status
    ON public.text_to_bi_agent_question_handling (status);
"""

MISSING_LABEL = (
    "CASE {value} WHEN 'glossary' THEN 'Thuật ngữ' WHEN 'metric' THEN 'Metric' "
    "WHEN 'expert_rule' THEN 'Expert rule' ELSE {value} END"
)

# A needs_review question with no handling row is pending; other questions need no handling, so they stay NULL.
HANDLING_STATUS = "CASE WHEN q.status = 'needs_review' THEN COALESCE(h.status, 'pending') END"
HANDLING_LABEL = (
    "CASE WHEN q.status = 'needs_review' THEN CASE COALESCE(h.status, 'pending') WHEN 'to_create' THEN 'Tạo mới' "
    "WHEN 'created' THEN 'Đã tạo mới' WHEN 'ignored' THEN 'Bỏ qua' ELSE 'Chưa xử lý' END END"
)

# Dates are local to REPORT_TIMEZONE, so "today" means the same day for every viewer and every server clock.
VIEWS_SQL = f"""
CREATE SCHEMA IF NOT EXISTS {REPORTING_SCHEMA};

CREATE OR REPLACE VIEW {REPORTING_SCHEMA}.agent_questions AS
SELECT
    q.id AS question_id,
    (q.created_on AT TIME ZONE '{REPORT_TIMEZONE}') AS asked_at,
    (q.created_on AT TIME ZONE '{REPORT_TIMEZONE}')::date AS asked_on,
    (now() AT TIME ZONE '{REPORT_TIMEZONE}')::date - (q.created_on AT TIME ZONE '{REPORT_TIMEZONE}')::date AS days_ago,
    u.username AS asked_by,
    d.dashboard_title,
    q.question,
    q.rewritten_question,
    q.status,
    CASE q.status WHEN 'resolved' THEN 'Thành công' WHEN 'needs_review' THEN 'Cần xác nhận' ELSE 'Lỗi' END
        AS status_label,
    (SELECT string_agg({MISSING_LABEL.format(value="kind")}, ', ')
        FROM json_array_elements_text(q.missing) AS kind) AS missing_items,
    (SELECT string_agg(item ->> 'name', ', ') FROM json_array_elements(q.glossary_terms) AS item) AS glossary_terms,
    (SELECT string_agg(item ->> 'name', ', ') FROM json_array_elements(q.metrics) AS item) AS metrics,
    (SELECT string_agg(item ->> 'name', ', ') FROM json_array_elements(q.expert_rules) AS item) AS expert_rules,
    q.error,
    q.duration_ms,
    {HANDLING_STATUS} AS handling_status,
    {HANDLING_LABEL} AS handling_label
FROM public.text_to_bi_agent_question AS q
LEFT JOIN public.text_to_bi_agent_question_handling AS h ON h.question_id = q.id
LEFT JOIN public.ab_user AS u ON u.id = q.user_id
LEFT JOIN public.dashboards AS d ON d.id = q.dashboard_id;

CREATE OR REPLACE VIEW {REPORTING_SCHEMA}.agent_question_gaps AS
SELECT
    q.id AS question_id,
    (q.created_on AT TIME ZONE '{REPORT_TIMEZONE}')::date AS asked_on,
    (now() AT TIME ZONE '{REPORT_TIMEZONE}')::date - (q.created_on AT TIME ZONE '{REPORT_TIMEZONE}')::date AS days_ago,
    {MISSING_LABEL.format(value="kind")} AS missing_item,
    {HANDLING_STATUS} AS handling_status
FROM public.text_to_bi_agent_question AS q
LEFT JOIN public.text_to_bi_agent_question_handling AS h ON h.question_id = q.id
CROSS JOIN LATERAL json_array_elements_text(q.missing) AS kind
WHERE q.status = 'needs_review';

-- One row per day and outcome for the last seven days, zero-filled, so a quiet day still takes its place on the axis.
CREATE OR REPLACE VIEW {REPORTING_SCHEMA}.agent_question_daily AS
WITH days AS (
    SELECT generate_series(
        (now() AT TIME ZONE '{REPORT_TIMEZONE}')::date - 6,
        (now() AT TIME ZONE '{REPORT_TIMEZONE}')::date,
        interval '1 day'
    )::date AS asked_on
),
outcomes (status, status_label) AS (
    VALUES ('resolved', 'Thành công'), ('needs_review', 'Cần xác nhận'), ('failed', 'Lỗi')
)
SELECT days.asked_on, outcomes.status, outcomes.status_label, count(q.id) AS question_count
FROM days
CROSS JOIN outcomes
LEFT JOIN public.text_to_bi_agent_question AS q
    ON (q.created_on AT TIME ZONE '{REPORT_TIMEZONE}')::date = days.asked_on AND q.status = outcomes.status
GROUP BY days.asked_on, outcomes.status, outcomes.status_label;
"""

DATASETS: dict[str, dict[str, Any]] = {
    "agent_questions": {
        "main_dttm_col": "asked_at",
        "metrics": [
            ("so_cau_hoi", "Số câu hỏi", "COUNT(*)"),
            ("so_thanh_cong", "Thành công", "SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END)"),
            ("so_can_xac_nhan", "Cần xác nhận", "SUM(CASE WHEN status = 'needs_review' THEN 1 ELSE 0 END)"),
            ("so_loi", "Lỗi", "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)"),
            ("so_chua_xu_ly", "Chưa xử lý", "SUM(CASE WHEN handling_status = 'pending' THEN 1 ELSE 0 END)"),
            ("so_can_tao_moi", "Cần tạo mới", "SUM(CASE WHEN handling_status = 'to_create' THEN 1 ELSE 0 END)"),
            ("so_da_tao_moi", "Đã tạo mới", "SUM(CASE WHEN handling_status = 'created' THEN 1 ELSE 0 END)"),
            ("so_bo_qua", "Bỏ qua", "SUM(CASE WHEN handling_status = 'ignored' THEN 1 ELSE 0 END)"),
        ],
    },
    "agent_question_gaps": {
        "main_dttm_col": "asked_on",
        "metrics": [
            ("so_lan_thieu", "Số lần thiếu", "COUNT(*)"),
            ("so_da_them_moi", "Đã thêm mới", "SUM(CASE WHEN handling_status = 'created' THEN 1 ELSE 0 END)"),
        ],
    },
    "agent_question_daily": {
        "main_dttm_col": "asked_on",
        "metrics": [("so_cau_hoi_theo_ngay", "Số câu hỏi", "SUM(question_count)")],
    },
}


def _filter(column: str, operator: str, value: Any) -> dict[str, Any]:
    return {"clause": "WHERE", "subject": column, "operator": operator, "comparator": value, "expressionType": "SIMPLE"}


TODAY = [_filter("days_ago", "==", 0)]
LAST_7_DAYS = [_filter("days_ago", "<=", 6)]


def _number(metric: str, filters: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "viz_type": "big_number_total",
        "metric": metric,
        "adhoc_filters": filters,
        "header_font_size": 0.4,
        "subheader_font_size": 0.15,
        "y_axis_format": ",d",
    }


# (chart title, dataset, width on the 12-column grid, row height, form data)
LAYOUT: list[list[tuple[str, str, int, int, dict[str, Any]]]] = [
    [
        ("Câu hỏi hôm nay", "agent_questions", 3, 24, _number("so_cau_hoi", TODAY)),
        ("Thành công hôm nay", "agent_questions", 3, 24, _number("so_thanh_cong", TODAY)),
        ("Cần xác nhận hôm nay", "agent_questions", 3, 24, _number("so_can_xac_nhan", TODAY)),
        ("Lỗi hôm nay", "agent_questions", 3, 24, _number("so_loi", TODAY)),
    ],
    [
        (
            "Câu hỏi 7 ngày gần nhất",
            "agent_question_daily",
            8,
            50,
            {
                "viz_type": "echarts_timeseries_bar",
                "x_axis": "asked_on",
                "time_grain_sqla": "P1D",
                "metrics": ["so_cau_hoi_theo_ngay"],
                "groupby": ["status_label"],
                "stack": "Stack",
                "adhoc_filters": [_filter("asked_on", "TEMPORAL_RANGE", "No filter")],
                "row_limit": 1000,
                "show_legend": True,
                "rich_tooltip": True,
                "x_axis_time_format": "%d/%m",
                "y_axis_format": ",d",
            },
        ),
        (
            "Phần còn thiếu (7 ngày)",
            "agent_question_gaps",
            4,
            50,
            {
                "viz_type": "echarts_timeseries_bar",
                "x_axis": "missing_item",
                "metrics": ["so_lan_thieu"],
                "groupby": [],
                "adhoc_filters": LAST_7_DAYS,
                "x_axis_sort": "so_lan_thieu",
                "x_axis_sort_asc": False,
                "row_limit": 10,
                "show_legend": False,
                "rich_tooltip": True,
                "y_axis_format": ",d",
            },
        ),
    ],
    # How administrators handled the needs_review questions, over all time, from the Xử lý câu hỏi module.
    [
        ("Chưa xử lý", "agent_questions", 3, 24, _number("so_chua_xu_ly", [])),
        ("Cần tạo mới", "agent_questions", 3, 24, _number("so_can_tao_moi", [])),
        ("Đã tạo mới từ câu hỏi", "agent_questions", 3, 24, _number("so_da_tao_moi", [])),
        ("Đã bỏ qua", "agent_questions", 3, 24, _number("so_bo_qua", [])),
    ],
    [
        (
            "Đã thêm mới theo loại",
            "agent_question_gaps",
            6,
            50,
            {
                "viz_type": "echarts_timeseries_bar",
                "x_axis": "missing_item",
                "metrics": ["so_da_them_moi"],
                "groupby": [],
                "adhoc_filters": [_filter("handling_status", "==", "created")],
                "x_axis_sort": "so_da_them_moi",
                "x_axis_sort_asc": False,
                "row_limit": 10,
                "show_legend": False,
                "rich_tooltip": True,
                "y_axis_format": ",d",
            },
        ),
        (
            "Kết quả xử lý câu hỏi",
            "agent_questions",
            6,
            50,
            {
                "viz_type": "echarts_timeseries_bar",
                "x_axis": "handling_label",
                "metrics": ["so_cau_hoi"],
                "groupby": [],
                "adhoc_filters": [_filter("status", "==", "needs_review")],
                "x_axis_sort": "so_cau_hoi",
                "x_axis_sort_asc": False,
                "row_limit": 10,
                "show_legend": False,
                "rich_tooltip": True,
                "y_axis_format": ",d",
            },
        ),
    ],
]

COLUMN_LABELS = {
    "asked_at": "Thời điểm hỏi",
    "asked_on": "Ngày hỏi",
    "days_ago": "Số ngày trước",
    "asked_by": "Người hỏi",
    "dashboard_title": "Dashboard",
    "question": "Câu hỏi",
    "rewritten_question": "Câu hỏi đã viết lại",
    "status": "Trạng thái (mã)",
    "status_label": "Trạng thái",
    "missing_items": "Còn thiếu",
    "missing_item": "Phần còn thiếu",
    "question_count": "Số câu hỏi",
    "glossary_terms": "Thuật ngữ",
    "metrics": "Metric",
    "expert_rules": "Expert rule",
    "error": "Lỗi",
    "duration_ms": "Thời gian xử lý (ms)",
    "handling_status": "Xử lý (mã)",
    "handling_label": "Xử lý",
}


def reporting_password() -> str:
    return os.getenv("TEXT_TO_BI_REPORTING_DB_PASSWORD", "reporting_dev_password")


def reporting_uri() -> str:
    database = os.getenv("SUPERSET_DB", "superset")
    return f"postgresql+psycopg2://{REPORTING_ROLE}:{reporting_password()}@superset-db:5432/{database}"


def create_reporting_views(engine: Any) -> None:
    """Create the views and the read-only role; the metadata database owner runs this, the role only reads."""
    from psycopg2 import sql

    database = os.getenv("SUPERSET_DB", "superset")
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(QUESTION_TABLE_DDL)
        cursor.execute(VIEWS_SQL)
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (REPORTING_ROLE,))
        role = sql.Identifier(REPORTING_ROLE)
        if cursor.fetchone() is None:
            cursor.execute(sql.SQL("CREATE ROLE {} LOGIN").format(role))
        cursor.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(reporting_password())))
        cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), role))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(REPORTING_SCHEMA), role))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(sql.Identifier(REPORTING_SCHEMA), role)
        )
        connection.commit()
    finally:
        connection.close()


def _position_json(rows: list[list[tuple[Any, int, int]]]) -> dict[str, Any]:
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
        for chart, width, height in row:
            chart_id = f"CHART-{chart.id}"
            position[row_id]["children"].append(chart_id)
            position[chart_id] = {
                "type": "CHART",
                "id": chart_id,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "width": width,
                    "height": height,
                    "chartId": chart.id,
                    "sliceName": chart.slice_name,
                    "uuid": str(chart.uuid),
                },
            }
    return position


def bootstrap() -> None:
    app = create_app()
    with app.app_context():
        from superset.connectors.sqla.models import SqlaTable, SqlMetric
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice

        from superset import db, security_manager

        create_reporting_views(db.engine)

        database = db.session.query(Database).filter(Database.database_name == DATABASE_NAME).one_or_none()
        if database is None:
            database = Database(database_name=DATABASE_NAME)
            db.session.add(database)
        database.sqlalchemy_uri = reporting_uri()
        # The Semantic Layer skips connections with this flag: reporting views are not business data to model.
        database.extra = json.dumps({**json.loads(database.extra or "{}"), "text_to_bi_internal": True})
        database.expose_in_sqllab = False
        database.allow_ctas = False
        database.allow_cvas = False
        database.allow_dml = False
        database.allow_run_async = False
        db.session.commit()

        datasets: dict[str, Any] = {}
        for table_name, spec in DATASETS.items():
            dataset = (
                db.session.query(SqlaTable)
                .filter(
                    SqlaTable.database_id == database.id,
                    SqlaTable.schema == REPORTING_SCHEMA,
                    SqlaTable.table_name == table_name,
                )
                .one_or_none()
            )
            if dataset is None:
                dataset = SqlaTable(
                    table_name=table_name, schema=REPORTING_SCHEMA, database=database, extra=MANAGED_MARKER
                )
                db.session.add(dataset)
                db.session.flush()
            dataset.fetch_metadata()
            dataset.main_dttm_col = spec["main_dttm_col"]
            for column in dataset.columns:
                column.verbose_name = COLUMN_LABELS.get(column.column_name, column.verbose_name)
                if column.column_name in ("asked_at", "asked_on"):
                    column.is_dttm = True
            existing = {metric.metric_name: metric for metric in dataset.metrics}
            for metric_name, verbose_name, expression in spec["metrics"]:
                metric = existing.get(metric_name)
                if metric is None:
                    metric = SqlMetric(metric_name=metric_name, table=dataset)
                    dataset.metrics.append(metric)
                metric.verbose_name = verbose_name
                metric.expression = expression
                metric.d3format = ",d"
            datasets[table_name] = dataset
        db.session.commit()

        admin = security_manager.find_user(username=os.getenv("SUPERSET_ADMIN_USERNAME", "admin"))
        owners = [admin] if admin else []
        # A chart is found by title among all governance datasets, so moving it to another view keeps the chart.
        governance_dataset_ids = [dataset.id for dataset in datasets.values()]
        rows: list[list[tuple[Any, int, int]]] = []
        for layout_row in LAYOUT:
            row = []
            for name, table_name, width, height, form_data in layout_row:
                dataset = datasets[table_name]
                chart = (
                    db.session.query(Slice)
                    .filter(Slice.slice_name == name, Slice.datasource_type == "table")
                    .filter(Slice.datasource_id.in_(governance_dataset_ids))
                    .one_or_none()
                )
                if chart is None:
                    chart = Slice(slice_name=name, datasource_type="table", datasource_id=dataset.id)
                    db.session.add(chart)
                chart.viz_type = form_data["viz_type"]
                chart.datasource_id = dataset.id
                chart.datasource_name = dataset.table_name
                chart.params = json.dumps({**form_data, "datasource": f"{dataset.id}__table"})
                chart.owners = owners
                row.append((chart, width, height))
            rows.append(row)
        db.session.flush()

        # Charts dropped from LAYOUT are removed, so the dashboard and the governance datasets stay in step.
        kept_chart_ids = [chart.id for row in rows for chart, _, _ in row]
        stale_charts = (
            db.session.query(Slice)
            .filter(Slice.datasource_type == "table", Slice.datasource_id.in_(governance_dataset_ids))
            .filter(Slice.id.notin_(kept_chart_ids))
            .all()
        )
        for chart in stale_charts:
            db.session.delete(chart)

        dashboard = db.session.query(Dashboard).filter(Dashboard.slug == DASHBOARD_SLUG).one_or_none()
        if dashboard is None:
            dashboard = Dashboard(slug=DASHBOARD_SLUG)
            db.session.add(dashboard)
        metadata = json.loads(dashboard.json_metadata or "{}")
        metadata.setdefault("refresh_frequency", 0)
        metadata.setdefault("native_filter_configuration", [])
        # Superset applies custom label colors on top of a named scheme, so both are set.
        metadata.setdefault("color_scheme", "supersetColors")
        metadata["label_colors"] = {**metadata.get("label_colors", {}), **STATUS_COLORS}
        dashboard.dashboard_title = DASHBOARD_TITLE
        dashboard.published = True
        dashboard.owners = owners
        dashboard.slices = [chart for row in rows for chart, _, _ in row]
        dashboard.position_json = json.dumps(_position_json(rows))
        dashboard.json_metadata = json.dumps(metadata)
        db.session.commit()

        chart_count = len(dashboard.slices)
        LOGGER.info("Governance dashboard ready: /superset/dashboard/%s/ (%s charts)", DASHBOARD_SLUG, chart_count)


if __name__ == "__main__":
    bootstrap()
