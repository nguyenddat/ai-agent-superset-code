from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

_COMPARISONS = {
    exp.EQ: "là",
    exp.NEQ: "khác",
    exp.GT: "lớn hơn",
    exp.GTE: "từ",
    exp.LT: "nhỏ hơn",
    exp.LTE: "không quá",
}
_AGGREGATE_WORDS = {"SUM": "Tổng", "AVG": "Trung bình", "MAX": "Giá trị lớn nhất của", "MIN": "Giá trị nhỏ nhất của"}

Part = dict[str, str]


class _Untold(Exception):
    """The formula uses something the sentence cannot tell faithfully."""


def _text(value: str) -> Part:
    return {"text": value}


def _value(node: exp.Expression) -> list[Part]:
    if isinstance(node, exp.Literal):
        return [_text(f"“{node.this}”" if node.is_string else node.this)]
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal):
        return [_text(f"-{node.this.this}")]
    if isinstance(node, exp.Boolean):
        return [_text("đúng" if node.this else "sai")]
    raise _Untold


def _condition(node: exp.Expression, column_part) -> list[Part]:
    if isinstance(node, exp.Paren):
        return _condition(node.this, column_part)
    if isinstance(node, (exp.And, exp.Or)):
        joiner = " và " if isinstance(node, exp.And) else " hoặc "
        return [*_condition(node.left, column_part), _text(joiner), *_condition(node.right, column_part)]
    if isinstance(node, exp.Not):
        return [_text("không phải ("), *_condition(node.this, column_part), _text(")")]
    if isinstance(node, exp.Is) and isinstance(node.left, exp.Column) and isinstance(node.right, exp.Null):
        return [column_part(node.left), _text(" trống")]
    if isinstance(node, exp.In) and isinstance(node.this, exp.Column) and node.expressions:
        values: list[Part] = []
        for index, item in enumerate(node.expressions):
            values += ([_text(", ")] if index else []) + _value(item)
        return [column_part(node.this), _text(" thuộc "), *values]
    if isinstance(node, exp.Between) and isinstance(node.this, exp.Column):
        low, high = _value(node.args["low"]), _value(node.args["high"])
        return [column_part(node.this), _text(" từ "), *low, _text(" đến "), *high]
    word = _COMPARISONS.get(type(node))
    if word and isinstance(node.left, exp.Column):
        suffix = [_text(" trở lên")] if isinstance(node, exp.GTE) else []
        return [column_part(node.left), _text(f" {word} "), *_value(node.right), *suffix]
    raise _Untold


def told_formula(expression: str, columns: list[dict[str, Any]]) -> list[Part] | None:
    """The formula as sentence parts; `columns` are the dataset's columns with their data dictionary labels."""
    labels = {column["name"]: column.get("label") or column["name"] for column in columns}

    def column_part(node: exp.Column) -> Part:
        if node.table or node.name not in labels:
            raise _Untold
        return {"column": node.name, "label": labels[node.name]}

    try:
        tree = sqlglot.parse_one(expression, read="postgres")
    except SqlglotError:
        return None
    if not isinstance(tree, (exp.Sum, exp.Avg, exp.Max, exp.Min, exp.Count)):
        return None
    measure, condition = tree.this, None
    try:
        if isinstance(measure, exp.Case):
            branches = measure.args.get("ifs") or []
            default = measure.args.get("default")
            if len(branches) != 1 or not (default is None or isinstance(default, exp.Null)):
                return None
            condition = _condition(branches[0].this, column_part)
            measure = branches[0].args.get("true")
        # COUNT of a constant and SUM of 1 both count the rows that meet the condition.
        counts_constant = isinstance(tree, exp.Count) and (measure is None or isinstance(measure, (exp.Literal, exp.Star)))
        sums_one = isinstance(tree, exp.Sum) and isinstance(measure, exp.Literal) and measure.this == "1"
        counted_rows = counts_constant or sums_one
        if counted_rows:
            sentence = [_text("Đếm số dòng")]
        elif isinstance(measure, exp.Column):
            word = "Đếm số" if isinstance(tree, exp.Count) else _AGGREGATE_WORDS[tree.key.upper()]
            sentence = [_text(f"{word} "), column_part(measure)]
        elif isinstance(measure, (exp.Literal, exp.Neg)) and not isinstance(tree, exp.Count):
            sentence = [_text(f"{_AGGREGATE_WORDS[tree.key.upper()]} giá trị "), *_value(measure)]
        else:
            return None
        if condition is not None:
            sentence += [_text(" có " if counted_rows else ", chỉ tính các dòng có "), *condition]
    except _Untold:
        return None
    return sentence


def doubtful_result(result: dict[str, Any]) -> str | None:
    """Why a provisional figure might be a wrong formula rather than a real answer, or None.

    A formula that filters on a value the data never holds still runs and answers with nothing, or with zero. So can a
    right formula over a quiet week, which is why the caller then checks the metric over all the data
    (`answers_anything`). A period outside the data is told apart by its coverage and is not doubted here.
    """
    if (result.get("coverage") or {}).get("status") == "none":
        return None
    if not result.get("total_rows"):
        return "empty"
    names = [metric["name"] for metric in result.get("metrics", [])]
    values = [row.get(name) for row in result.get("rows", []) for name in names]
    complete = result.get("row_count") == result.get("total_rows") and not result.get("truncated")
    if complete and values and all(value in (0, None) for value in values):
        return "zero"
    return None


def answers_anything(answer: dict[str, Any], metric_name: str) -> bool:
    """Whether the metric, run over all the data with no filter, gives any value other than zero."""
    for row in answer.get("rows", []):
        try:
            # The Semantic Layer returns numbers as numbers or as decimal strings such as "0.0000".
            if float(row.get(metric_name)) != 0:
                return True
        except (TypeError, ValueError):
            continue
    return False
