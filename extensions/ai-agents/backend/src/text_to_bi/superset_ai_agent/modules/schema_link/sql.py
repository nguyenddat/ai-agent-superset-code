from typing import Any

from sqlglot import exp

from ..chat.query import whole_day_filters
from .goal import Goal
from .graph import SchemaGraph
from .paths import JoinTree

DIALECTS = {"postgresql": "postgres", "postgres": "postgres", "mysql": "mysql", "sqlite": "sqlite"}
_AGGREGATES = {"SUM": exp.Sum, "AVG": exp.Avg, "MIN": exp.Min, "MAX": exp.Max}
_COMPARISONS = {"==": exp.EQ, "!=": exp.NEQ, "<": exp.LT, "<=": exp.LTE, ">": exp.GT, ">=": exp.GTE}


def _literal(value: Any) -> exp.Expression:
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)):
        return exp.Literal.number(value)
    return exp.Literal.string(str(value))


def _condition(column: exp.Expression, operator: str, value: Any) -> exp.Expression:
    if operator in ("IN", "NOT IN"):
        membership = exp.In(this=column, expressions=[_literal(item) for item in value])
        return exp.Not(this=membership) if operator == "NOT IN" else membership
    return _COMPARISONS[operator](this=column, expression=_literal(value))


def _alias(name: str, taken: set[str]) -> str:
    candidate, number = name, 2
    while candidate in taken:
        candidate, number = f"{name}_{number}", number + 1
    taken.add(candidate)
    return candidate


def build_sql(goal: Goal, tree: JoinTree, graph: SchemaGraph) -> str:
    dialect = DIALECTS.get(graph.dialect, "postgres")
    aliases = {table: f"t{index}" for index, table in enumerate(tree.tables)}

    def table(table_id: int) -> exp.Expression:
        node = graph.tables[table_id]
        return exp.table_(node["table"], db=node.get("schema"), alias=aliases[table_id], quoted=True)

    def column(table_id: int, name: str) -> exp.Expression:
        return exp.column(name, table=aliases[table_id], quoted=True)

    query = exp.select().from_(table(tree.root))
    for step in tree.steps:
        joined_on = exp.EQ(this=column(step.start, step.start_column), expression=column(step.end, step.end_column))
        query = query.join(table(step.end), on=joined_on)

    taken: set[str] = set()
    groups = []
    for item in goal.group_by:
        expression = column(item.table, item.column)
        if item.time_grain:
            expression = exp.Anonymous(this="DATE_TRUNC", expressions=[exp.Literal.string(item.time_grain), expression])
        groups.append(expression)
        query = query.select(exp.alias_(expression.copy(), _alias(item.column, taken), quoted=True))
    for measure in goal.measures:
        if measure.column is None:
            aggregated = exp.Count(this=exp.Star())
        elif measure.aggregation == "COUNT":
            aggregated = exp.Count(this=column(measure.table, measure.column))
        elif measure.aggregation == "COUNT_DISTINCT":
            aggregated = exp.Count(this=exp.Distinct(expressions=[column(measure.table, measure.column)]))
        else:
            aggregated = _AGGREGATES[measure.aggregation](this=column(measure.table, measure.column))
        name = (measure.indicator or {}).get("code") or f"{measure.aggregation.lower()}_{measure.column or 'dong'}"
        query = query.select(exp.alias_(aggregated, _alias(name, taken), quoted=True))

    conditions = []
    for item in goal.filters:
        timestamp = (graph.column(item.table, item.column) or {}).get("temporal_kind") == "timestamp"
        sent = {"column": item.column, "operator": item.operator, "value": item.value}
        for part in whole_day_filters(sent, timestamp):
            conditions.append(_condition(column(item.table, item.column), part["operator"], part["value"]))
    for item in goal.row_kinds:
        conditions.append(_condition(column(item.table, item.column), "==", item.value))
    if conditions:
        query = query.where(exp.and_(*conditions))
    if groups:
        query = query.group_by(*[expression.copy() for expression in groups])
        query = query.order_by(*[expression.copy() for expression in groups])
    return query.limit(goal.limit).sql(dialect=dialect, pretty=True)
