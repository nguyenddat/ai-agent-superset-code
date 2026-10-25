"""PostgreSQL SQLGlot scanner for prose-only expert-rule fields.

This module never executes SQL.  It scans parser token boundaries so SQL may be
detected after explanatory prose, while only rejecting SQLGlot-confirmed ASTs.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError
from sqlglot.tokens import Token, Tokenizer

_LEXICAL_FORBIDDEN = ("\x00", ";", "--", "/*", "*/", "$$", "#")
_STATEMENT_TYPES = (
    exp.Query,
    exp.Values,
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Alter,
    exp.Drop,
    exp.Grant,
    exp.Revoke,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Set,
    exp.Use,
    exp.Attach,
    exp.Pragma,
)


def _command_is_documented_control(node: exp.Command) -> bool:
    """Classify SQLGlot's deliberate Command fallback, never free text alone."""
    command = str(node.args.get("this") or "").upper()
    expression_node = node.args.get("expression")
    expression = str(getattr(expression_node, "this", expression_node) or "").strip()
    # SQLGlot preserves unsupported statements as Command, with either a
    # separate expression or all text in ``this`` depending on the dialect.
    if not expression and " " in command:
        command, expression = command.split(" ", 1)
    if command == "EXPLAIN":
        return bool(expression)
    try:
        return _tokens_are_dialect_control(Tokenizer(dialect="postgres").tokenize(f"{command} {expression}"))
    except TokenError:
        return True


def _tokens_are_dialect_control(tokens: list[Token]) -> bool:
    """Recognize the small documented control grammar SQLGlot cannot parse.

    This is token-structure classification after PostgreSQL parsing failed, not
    a text keyword detector: each branch requires its complete command shape.
    """
    words = [token.text.upper() for token in tokens]
    first = words[0] if words else ""
    # Every rule is a complete token grammar supplied to cover PostgreSQL and
    # documented control statements that SQLGlot represents as Command or
    # cannot parse in PostgreSQL mode.
    if first == "SHOW":
        return len(words) == 2 and words[1] in {"ALL", "SEARCH_PATH", "DATABASES", "TABLES", "SCHEMAS"}
    if first in {"DESCRIBE", "DESC", "ANALYZE", "LISTEN", "NOTIFY"}:
        return len(words) == 2
    if first == "EXPLAIN":
        return len(words) >= 2 and words[1] in {"SELECT", "ANALYZE", "QUERY"}
    if first == "TRUNCATE":
        return len(words) >= 2 and (words[1] == "TABLE" and len(words) >= 3 or words[1] != "TABLE")
    if first == "MERGE":
        return len(words) >= 3 and words[1] == "INTO"
    if first == "CALL":
        return len(words) >= 2
    if first in {"EXEC", "EXECUTE", "COPY"}:
        return len(words) >= 2
    if first == "LOAD":
        return len(words) >= 2
    if first in {"START", "SAVEPOINT", "DECLARE", "LOCK"}:
        return (first == "START" and words == ["START", "TRANSACTION"]) or (first != "START" and len(words) >= 2)
    if first == "DO":
        return len(words) >= 2 and words[1] == "LANGUAGE"
    if first == "DEALLOCATE":
        return words == ["DEALLOCATE", "ALL"] or (len(words) == 3 and words[1] == "PREPARE")
    if first in {"RESET", "DISCARD"}:
        return words == [first, "ALL"]
    if first == "REINDEX":
        return len(words) >= 3 and words[1] in {"TABLE", "INDEX", "DATABASE"}
    if first == "DROP":
        return (len(words) >= 2 and words[1] in {"ROLE", "SEQUENCE"}) or (len(words) >= 4 and words[1:3] == ["IF", "EXISTS"] and words[3] in {"TABLE", "VIEW", "INDEX", "ROLE", "SEQUENCE"})
    if first in {"CREATE", "ALTER"}:
        return len(words) >= 2 and words[1] in {"ROLE", "SEQUENCE"}
    if first == "SET":
        return len(words) >= 3 and words[1] in {"ROLE", "SEARCH_PATH", "TRANSACTION", "SESSION"}
    if first == "COMMIT":
        return len(words) in {1, 2}
    if first in {"PRAGMA", "VACUUM"}:
        return bool(words)
    if first == "ATTACH":
        return len(words) == 5 and words[1] == "DATABASE" and words[3] == "AS"
    return False


def _is_sql_ast(node: exp.Expression) -> bool:
    if isinstance(node, _STATEMENT_TYPES):
        return True
    if isinstance(node, exp.Command):
        return _command_is_documented_control(node)
    return False


def contains_sql_or_control(value: str) -> bool:
    """Return whether PostgreSQL SQL/control syntax occurs at a token boundary."""
    if any(marker in value for marker in _LEXICAL_FORBIDDEN):
        return True
    try:
        tokens = Tokenizer(dialect="postgres").tokenize(value)
    except TokenError:
        return True
    for token in tokens:
        candidate = value[token.start :]
        try:
            candidate_tokens = Tokenizer(dialect="postgres").tokenize(candidate)
        except TokenError:
            return True
        if _tokens_are_dialect_control(candidate_tokens):
            return True
        try:
            trees = sqlglot.parse(candidate, read="postgres")
        except ParseError:
            continue
        if len(trees) != 1 or trees[0] is None:
            continue
        if _is_sql_ast(trees[0]):
            return True
    return False
