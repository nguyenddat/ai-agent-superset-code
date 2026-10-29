from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError


def _is_filter(column: exp.Column) -> bool:
    """Whether a column picks the rows a metric covers rather than being the value it aggregates.

    That is a column in a CASE condition, in an aggregate's FILTER (WHERE ...) clause, or in a window's PARTITION BY or
    ORDER BY.
    """
    node: exp.Expression = column
    while node.parent is not None:
        parent = node.parent
        if isinstance(parent, exp.If) and node is parent.args.get("this"):
            return True
        if isinstance(parent, exp.Filter) and node is parent.expression:
            return True
        if isinstance(parent, exp.Window):
            partition = parent.args.get("partition_by") or []
            if node is parent.args.get("order") or any(node is item for item in partition):
                return True
        node = parent
    return False


def metric_columns(expression: str | None, column_names: list[str], dialect: str | None) -> list[dict[str, Any]] | None:
    """The dataset columns a metric expression uses, each with its role: ``measure`` or ``filter``.

    Columns are matched to ``column_names``, exactly or else ignoring case, and anything else the parser takes for a
    column (an alias, a typo) is left out. A column used both ways counts as a measure. None when the expression cannot
    be parsed, such as one holding Jinja templating, so callers fall back to the dataset as a whole.
    """
    if not expression or not expression.strip():
        return []
    try:
        tree = sqlglot.parse_one(expression, read=dialect)
    except SqlglotError:
        return None
    if tree is None:
        return None
    exact = set(column_names)
    folded = {name.lower(): name for name in column_names}
    roles: dict[str, str] = {}
    for column in tree.find_all(exp.Column):
        name = column.name if column.name in exact else folded.get(column.name.lower())
        if name is None:
            continue
        role = "filter" if _is_filter(column) else "measure"
        roles[name] = "measure" if roles.get(name) == "measure" else role
    # Dataset column order keeps the result stable between requests.
    return [{"name": name, "role": roles[name]} for name in column_names if name in roles]
