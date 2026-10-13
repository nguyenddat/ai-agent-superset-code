from typing import Any

from langchain.tools import tool


def discover_chart_capabilities() -> dict[str, Any]:
    """Read the supported XY chart mappings and field schema from this Superset instance."""
    try:
        from superset.mcp_service.chart.chart_utils import _resolve_viz_type
        from superset.mcp_service.chart.schemas import XYChartConfig

        schema = XYChartConfig.model_json_schema()
        mappings = {}
        for kind in XYChartConfig.model_fields["kind"].annotation.__args__:
            config = XYChartConfig(
                x={"name": "x"},
                y=[{"name": "y", "aggregate": "SUM"}],
                kind=kind,
            )
            mappings[_resolve_viz_type(config)] = kind
        return {
            "available": True,
            "source": "Superset MCP XYChartConfig và map_xy_config",
            "viz_types": sorted(mappings),
            "kinds_by_viz_type": mappings,
            "field_roles": {
                "x": "Một trường danh mục hoặc thời gian",
                "y": "Ít nhất một chỉ số hoặc trường có phép tổng hợp",
                "group_by": "Các trường tùy chọn để chia chuỗi dữ liệu",
                "time_grain": "Mức thời gian tùy chọn; áp dụng khi trục X là thời gian",
            },
            "required_fields": schema.get("required", []),
            "schema": schema,
            "scope": "Các loại XY được khai báo trong schema Superset; không đại diện mọi loại biểu đồ của instance.",
        }
    except Exception as exc:
        return {
            "available": False,
            "viz_types": [],
            "error": f"Không đọc được năng lực biểu đồ từ Superset: {exc}",
        }


@tool
def get_chart_capabilities() -> dict[str, Any]:
    """Khám phá loại biểu đồ XY và vai trò trường mà phiên bản Superset hiện tại hỗ trợ."""
    return discover_chart_capabilities()


@tool
def get_superset_chart_types() -> dict[str, Any]:
    """Liệt kê các loại chart được đăng ký bởi chart tools của Superset hiện tại."""
    try:
        from superset.mcp_service.chart.tool.get_chart_type_schema import VALID_CHART_TYPES

        return {"available": True, "chart_types": VALID_CHART_TYPES}
    except Exception as exc:
        return {"available": False, "chart_types": [], "error": str(exc)}


@tool
def get_superset_chart_type_schema(chart_type: str) -> dict[str, Any]:
    """Lấy JSON Schema và ví dụ cấu hình từ chart tool của Superset."""
    try:
        from superset.mcp_service.chart.tool.get_chart_type_schema import (
            _get_chart_type_schema_impl,
        )

        return _get_chart_type_schema_impl(chart_type)
    except Exception as exc:
        return {"error": f"Không đọc được chart schema từ Superset: {exc}"}
