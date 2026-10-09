"""Create an unsaved Superset Explore chart backed by Data Builder SQL."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from urllib.parse import urlencode

from ..core.settings import config
from ..core.superset_client import superset_client
from .context.agent import BIAgentContext, MetadataResolutionContext
from .context.metadata_resolution import MetadataResolution
from .tools.query_sql import _dataset_detail, _dialect, _prepare_sql

logger = logging.getLogger(__name__)


def create_chat_chart(
    sql: str,
    metadata_context: MetadataResolutionContext,
    base_context: BIAgentContext,
    resolution: MetadataResolution,
) -> tuple[str | None, str | None]:
    """Register a deterministic virtual dataset and return its Explore URL."""
    dataset_id = resolution.dataset_id
    if dataset_id is None:
        return None, "Metadata Resolution không có dataset để dựng biểu đồ."
    try:
        detail = _dataset_detail(dataset_id, base_context["dashboard_id"], base_context["allowed_dataset_ids"])
        if "error" in detail:
            raise ValueError(detail["error"])
        dialect = _dialect((detail.get("database") or {}).get("backend"))
        if not dialect:
            raise ValueError("Không xác định được SQL dialect của dataset.")
        executable_sql, error = _prepare_sql(sql, detail, dialect)
        if error or not executable_sql:
            raise ValueError(error or "Không chuẩn bị được SQL nguồn cho chart.")

        config_json = resolution.config
        stable_key = json.dumps(
            {"dataset": dataset_id, "sql": executable_sql, "config": config_json},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        table_name = f"text_to_bi_chat_{dataset_id}_{hashlib.sha256(stable_key.encode()).hexdigest()[:16]}"
        chart_dataset_id = _find_or_create_dataset(detail, table_name, executable_sql)

        from superset.mcp_service.chart.chart_utils import map_config_to_form_data
        from superset.mcp_service.chart.schemas import parse_chart_config

        chart_config = dict(config_json)
        chart_config.setdefault("chart_type", resolution.chart_type or "xy")
        parsed_config = parse_chart_config(chart_config)
        form_data = map_config_to_form_data(parsed_config, dataset_id=chart_dataset_id)
        form_data["datasource"] = f"{chart_dataset_id}__table"
        if str(form_data.get("viz_type", "")).startswith("echarts_"):
            # Keep axis titles clear of category labels and tick values in the
            # compact chart iframe used by the chat drawer.
            form_data["x_axis_title_margin"] = 40
            form_data["y_axis_title_margin"] = 40
        x_ref = getattr(parsed_config, "x", None) or getattr(parsed_config, "dimension", None)
        x_name = getattr(x_ref, "name", None)
        source_columns = detail.get("columns") or []
        temporal_columns = {
            column.get("column_name")
            for column in source_columns
            if isinstance(column, dict) and column.get("is_dttm") is True
        }
        x_is_temporal = bool(x_name and x_name in temporal_columns)
        time_column = _plan_time_column(metadata_context, detail)

        # A single calendar day defaults to Superset's daily bucket, which
        # collapses an intraday temperature trend to one point (a line chart
        # then appears blank). Preserve a planned grain when supplied; for an
        # explicit today-only request, use hourly buckets as the useful default.
        time_grain = _chart_time_grain(metadata_context, config_json)
        if x_is_temporal and time_grain:
            form_data["time_grain_sqla"] = time_grain

        # A global time_range is only valid when the chart's time axis is the
        # temporal column. For numeric/category distributions, filter the
        # actual timestamp explicitly so Superset cannot compare a number to a date.
        form_data["time_range"] = (
            resolution.time_range if resolution.time_range and x_is_temporal else "No filter"
        )
        if resolution.time_range and isinstance(form_data.get("adhoc_filters"), list):
            # The mapper adds a default temporal adhoc filter with "No filter".
            form_data["adhoc_filters"] = [
                item
                for item in form_data["adhoc_filters"]
                if not (
                    isinstance(item, dict)
                    and item.get("operator") == "TEMPORAL_RANGE"
                    and item.get("comparator") == "No filter"
                )
            ]
            if not x_is_temporal:
                if not time_column:
                    raise ValueError("Không xác định được cột thời gian để áp dụng khoảng ngày cho biểu đồ phân phối.")
                form_data["adhoc_filters"].append({
                    "clause": "WHERE",
                    "expressionType": "SIMPLE",
                    "subject": time_column,
                    "operator": "TEMPORAL_RANGE",
                    "comparator": resolution.time_range,
                })
        comparisons = config_json.get("time_compare")
        if isinstance(comparisons, list) and comparisons:
            form_data["time_compare"] = comparisons

        # Compile and execute Superset's chart query before exposing the chart
        # URL. This uses Superset's own query pipeline, so bad metric/column/
        # filter mappings surface here instead of after the chat response.
        from superset.mcp_service.chart.tool.generate_chart import _compile_chart
        from superset import security_manager
        from superset.utils.core import override_user

        user = security_manager.get_user_by_id(base_context["user_id"])
        if user is None:
            raise ValueError("Không xác định được người dùng hiện tại để kiểm tra quyền compile chart.")
        # The chat runs the agents in a worker thread with an app context but no
        # request context. Reinstall the authenticated requester on Flask g so
        # Superset's native chart access checks execute under that same user.
        with override_user(user):
            compiled = _compile_chart(form_data, chart_dataset_id)
        if not compiled.success:
            raise ValueError(f"Superset không compile được biểu đồ: {compiled.error or 'Lỗi truy vấn không xác định.'}")
        if compiled.row_count == 0:
            raise ValueError("Chart query chạy thành công nhưng không có điểm dữ liệu trong khoảng thời gian và bộ lọc đã chọn.")
        if form_data.get("viz_type") == "echarts_timeseries_line" and compiled.row_count == 1:
            raise ValueError("Chart đường chỉ có một điểm dữ liệu; cần thêm độ phân giải thời gian để thể hiện xu hướng.")

        # Let the authenticated browser turn legacy form_data into a cached key.
        # A relative same-origin URL also works behind reverse proxies and avoids
        # exposing Superset's internal service hostname to the browser.
        explore_url = "/superset/explore/?" + urlencode({
            "form_data": json.dumps(form_data, ensure_ascii=False, separators=(",", ":")),
            "standalone": "true",
        })
        return explore_url, None
    except Exception as exc:
        logger.exception("Could not create Superset chart from Data Builder SQL (dataset_id=%s)", dataset_id)
        return None, str(exc)[:1200]


def _find_or_create_dataset(source: dict[str, Any], table_name: str, sql: str) -> int:
    base_url = config.superset_base_url.rstrip("/")
    query = f"(filters:!((col:table_name,opr:eq,value:{table_name})),page:0,page_size:100)"
    response = superset_client.get(f"{base_url}/api/v1/dataset/?{urlencode({'q': query})}", timeout=30)
    if response.ok:
        items = response.json().get("result") or []
        for item in items:
            if item.get("table_name") == table_name and item.get("id"):
                existing = superset_client.get(f"{base_url}/api/v1/dataset/{item['id']}", timeout=30)
                if existing.ok and (existing.json().get("result") or {}).get("sql") == sql:
                    return int(item["id"])

    database_id = (source.get("database") or {}).get("id")
    if not isinstance(database_id, int):
        raise ValueError("Dataset nguồn không có database_id hợp lệ.")
    payload = {
        "database": database_id,
        "schema": source.get("schema") or None,
        "table_name": table_name,
        "sql": sql,
        "normalize_columns": True,
    }
    created = superset_client.post(f"{base_url}/api/v1/dataset/", json=payload, timeout=90)
    try:
        body = created.json()
    except ValueError:
        body = {}
    if not created.ok or not isinstance(body.get("id"), int):
        message = body.get("message") or body.get("errors") or f"Superset HTTP {created.status_code}"
        raise RuntimeError(f"Không tạo được virtual dataset cho chart: {message}")
    return body["id"]


def _plan_time_column(context: MetadataResolutionContext, source_detail: dict[str, Any]) -> str | None:
    sources = context.get("data_sources") or []
    for source in sources:
        if not isinstance(source, dict):
            continue
        for item in source.get("filters") or []:
            if isinstance(item, dict) and item.get("operator") == "relative_time":
                field = item.get("field")
                if isinstance(field, str) and field:
                    return field
    columns = source_detail.get("columns") or []
    for column in columns:
        if isinstance(column, dict) and column.get("is_dttm") is True:
            name = column.get("column_name")
            if isinstance(name, str) and name:
                return name
    main_column = source_detail.get("main_dttm_col")
    return main_column if isinstance(main_column, str) and main_column else None


def _chart_time_grain(context: MetadataResolutionContext, chart_config: dict[str, Any]) -> str | None:
    configured = chart_config.get("time_grain") or context.get("time_grain")
    if isinstance(configured, str) and configured.strip():
        value = configured.strip()
        aliases = {
            "hour": "PT1H", "hourly": "PT1H", "1 hour": "PT1H",
            "day": "P1D", "daily": "P1D", "week": "P1W", "weekly": "P1W",
            "month": "P1M", "monthly": "P1M", "year": "P1Y", "yearly": "P1Y",
        }
        return aliases.get(value.casefold(), value)

    for source in context.get("data_sources") or []:
        if not isinstance(source, dict):
            continue
        for item in source.get("filters") or []:
            if not isinstance(item, dict) or item.get("operator") != "relative_time":
                continue
            value = item.get("value")
            if isinstance(value, str) and ("today" in value.casefold() or "hôm nay" in value.casefold()):
                return "PT1H"
    return None
