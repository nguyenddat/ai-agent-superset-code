"""The goal of a query over base tables: what to measure, what to group by, what to filter on, which kind of rows.

A goal names tables by dataset ID and columns by name, as the schema graph lists them; nothing else is trusted. An
indicator measure names an indicator code instead, such as `nhiet_do_c`: it becomes the value column of the table
keeping one value per indicator, filtered on the catalog's code, aggregated as the catalog says (`TRUNG_BINH` → AVG).

Each part records why it is there (`source`), which the analysis view shows. Until linking from a question exists, an
administrator writes the goal by hand, so every reference is checked against the graph with a message saying what is
wrong.
"""

from dataclasses import dataclass, field
from typing import Any

from .graph import SchemaGraph

AGGREGATIONS = ("SUM", "AVG", "MIN", "MAX", "COUNT", "COUNT_DISTINCT")
OPERATORS = ("==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN")
TIME_GRAINS = ("hour", "day", "week", "month", "quarter", "year")
# From finest to coarsest; a query may group a kind of row at its own grain or coarser, and `instant` rows at any.
GRAIN_ORDER = ("instant", "hour", "day", "week", "month", "quarter", "year")
DEFAULT_LIMIT = 1000
MAX_LIMIT = 10_000


class GoalError(ValueError):
    """The goal does not fit the schema graph; the message says what to change."""


@dataclass
class Measure:
    table: int
    column: str | None
    aggregation: str
    label: str
    source: str
    indicator: dict[str, Any] | None = None


@dataclass
class GroupBy:
    table: int
    column: str
    label: str
    time_grain: str | None = None


@dataclass
class Filter:
    table: int
    column: str
    operator: str
    value: Any
    label: str
    source: str = "mục tiêu"


@dataclass
class RowKind:
    table: int
    column: str
    value: str
    label: str
    grain: str


@dataclass
class Goal:
    measures: list[Measure]
    group_by: list[GroupBy] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    row_kinds: list[RowKind] = field(default_factory=list)
    limit: int = DEFAULT_LIMIT

    @property
    def root(self) -> int:
        return self.measures[0].table

    @property
    def terminals(self) -> list[int]:
        tables = [self.root, *(item.table for item in self.group_by), *(item.table for item in self.filters)]
        tables += [item.table for item in self.row_kinds]
        return list(dict.fromkeys(tables))


def _table(graph: SchemaGraph, raw: dict[str, Any], what: str) -> int:
    table = raw.get("dataset_id")
    if table not in graph.tables:
        raise GoalError(f"{what}: bảng {table!r} không có trong đồ thị (chỉ base table bạn được xem).")
    return table


def _column(graph: SchemaGraph, table: int, name: Any, what: str) -> dict[str, Any]:
    column = graph.column(table, name) if isinstance(name, str) else None
    if column is None:
        raise GoalError(f"{what}: cột {name!r} không có ở bảng {graph.table_name(table)}.")
    return column


def _indicator_measure(graph: SchemaGraph, raw: dict[str, Any]) -> tuple[Measure, Filter]:
    code = raw["indicator"]
    for catalog_id, catalog in graph.tables.items():
        model = catalog.get("indicator_model") or {}
        if model.get("kind") != "catalog":
            continue
        indicator = next(
            (item for item in (catalog.get("indicators") or {}).get("indicators", []) if item.get("code") == code), None,
        )
        if indicator is None:
            continue
        # The values table is the one whose indicator column has an approved relationship to this catalog's key.
        values_id, values_model = next(
            (
                (edge.from_table, graph.tables[edge.from_table]["indicator_model"])
                for edge in graph.edges
                if edge.to_table == catalog_id and edge.to_column == model["key_column"]
                and (graph.tables[edge.from_table].get("indicator_model") or {}).get("kind") == "values"
                and graph.tables[edge.from_table]["indicator_model"]["indicator_column"] == edge.from_column
            ),
            (None, None),
        )
        if values_id is None:
            raise GoalError(f"Chỉ số {code}: chưa có bảng giá trị nào nối tới {catalog['table']} bằng quan hệ đã duyệt.")
        value_column = values_model["value_columns"].get(str(indicator.get("value_kind")))
        if value_column is None:
            raise GoalError(f"Chỉ số {code}: bảng giá trị chưa khai báo cột cho kiểu {indicator.get('value_kind')}.")
        aggregation = raw.get("aggregation") or indicator.get("aggregation")
        if aggregation in (None, "NONE"):
            raise GoalError(f"Chỉ số {code} ({indicator.get('name')}) không gộp được; chọn phép gộp cụ thể.")
        if aggregation not in AGGREGATIONS:
            raise GoalError(f"Chỉ số {code}: phép gộp {aggregation!r} không hợp lệ.")
        label = raw.get("label") or indicator.get("name") or code
        measure = Measure(
            values_id, value_column, aggregation, label,
            "chỉ số " + ("(phép gộp chọn tay)" if raw.get("aggregation") else f"(phép gộp theo danh mục: {indicator.get('aggregation_code')})"),
            {"code": code, "name": indicator.get("name"), "unit": indicator.get("unit"), "catalog": catalog_id},
        )
        code_filter = Filter(catalog_id, model["code_column"], "==", code, f"Chỉ số = {indicator.get('name') or code}", "chỉ số")
        return measure, code_filter
    raise GoalError(f"Chỉ số {code!r} không có trong danh mục chỉ số nào.")


def _measure(graph: SchemaGraph, raw: dict[str, Any]) -> Measure:
    table = _table(graph, raw, "Đo")
    aggregation = raw.get("aggregation")
    if aggregation not in AGGREGATIONS:
        raise GoalError(f"Đo: phép gộp {aggregation!r} không hợp lệ.")
    if raw.get("column") is None:
        if aggregation != "COUNT":
            raise GoalError("Đo: không có cột thì chỉ đếm số dòng (COUNT).")
        return Measure(table, None, "COUNT", raw.get("label") or f"Số dòng {graph.table_name(table)}", "đếm dòng")
    column = _column(graph, table, raw["column"], "Đo")
    allowed = column.get("aggregations") or []
    if aggregation not in ("COUNT", "COUNT_DISTINCT"):
        if column.get("role") != "measure":
            raise GoalError(f"Đo: cột {column['name']} không phải cột đo lường, chỉ đếm được.")
        if allowed and aggregation not in allowed:
            raise GoalError(f"Đo: {column['name']} chỉ gộp được bằng {', '.join(allowed)}.")
    return Measure(table, column["name"], aggregation, raw.get("label") or column["label"], "cột đo lường")


def resolve_goal(raw: dict[str, Any], graph: SchemaGraph) -> Goal:
    """The goal with every table and column checked against the graph. Raises GoalError."""
    if not isinstance(raw, dict) or not isinstance(raw.get("measures"), list) or not raw["measures"]:
        raise GoalError("Mục tiêu cần ít nhất một phép đo (measures).")
    measures, filters = [], []
    for item in raw["measures"]:
        if not isinstance(item, dict):
            raise GoalError("Mỗi phép đo phải là một object.")
        if item.get("indicator"):
            measure, code_filter = _indicator_measure(graph, item)
            measures.append(measure)
            filters.append(code_filter)
        else:
            measures.append(_measure(graph, item))
    if len({measure.table for measure in measures}) > 1:
        raise GoalError("Các phép đo phải nằm trên cùng một bảng gốc; tách thành nhiều câu hỏi.")

    group_by = []
    for item in raw.get("group_by") or []:
        table = _table(graph, item, "Chia theo")
        column = _column(graph, table, item.get("column"), "Chia theo")
        grain = item.get("time_grain")
        if grain is not None and (grain not in TIME_GRAINS or not column.get("temporal_kind")):
            raise GoalError(f"Chia theo: {column['name']} không gom theo {grain!r} được.")
        group_by.append(GroupBy(table, column["name"], item.get("label") or column["label"], grain))

    for item in raw.get("filters") or []:
        table = _table(graph, item, "Lọc")
        column = _column(graph, table, item.get("column"), "Lọc")
        operator, value = item.get("operator"), item.get("value")
        if operator not in OPERATORS or value is None or (operator in ("IN", "NOT IN")) != isinstance(value, list):
            raise GoalError(f"Lọc {column['name']}: toán tử hoặc giá trị không hợp lệ.")
        filters.append(Filter(table, column["name"], operator, value, item.get("label") or f"{column['label']} {operator} {value}"))

    row_kinds = []
    for item in raw.get("row_kinds") or []:
        table = _table(graph, item, "Loại dòng")
        time = graph.tables[table].get("time") or {}
        kind = next((kind for kind in time.get("row_kinds", []) if kind["value"] == item.get("value")), None)
        if not time.get("row_kind_column") or kind is None:
            raise GoalError(f"Loại dòng {item.get('value')!r} không có ở bảng {graph.table_name(table)}.")
        row_kinds.append(RowKind(table, time["row_kind_column"], kind["value"], kind.get("label") or kind["value"], kind["grain"]))

    limit = raw.get("limit", DEFAULT_LIMIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise GoalError(f"limit phải từ 1 đến {MAX_LIMIT}.")
    return Goal(measures, group_by, filters, row_kinds, limit)


def grain_problems(goal: Goal, tables: list[int], graph: SchemaGraph) -> list[dict[str, Any]]:
    """Tables in the join that mix grains without a chosen kind of row, or group finer than the chosen kind's grain."""
    chosen = {item.table: item for item in goal.row_kinds}
    problems = []
    for table in tables:
        kinds = (graph.tables[table].get("time") or {}).get("row_kinds", [])
        if len(kinds) > 1 and table not in chosen:
            problems.append({
                "table": table, "kind": "row_kind_missing",
                "message": f"{graph.table_name(table)} trộn nhiều loại dòng; chọn một: "
                           + ", ".join(f"{kind['value']} ({kind['grain']})" for kind in kinds),
                "options": [kind["value"] for kind in kinds],
            })
    for item in goal.group_by:
        row_kind = chosen.get(item.table)
        if item.time_grain and row_kind and row_kind.grain != "instant" and (
            GRAIN_ORDER.index(item.time_grain) < GRAIN_ORDER.index(row_kind.grain)
        ):
            problems.append({
                "table": item.table, "kind": "grain_too_fine",
                "message": f"{row_kind.label} có grain {row_kind.grain}, không chia theo {item.time_grain} được.",
                "options": [],
            })
    return problems
