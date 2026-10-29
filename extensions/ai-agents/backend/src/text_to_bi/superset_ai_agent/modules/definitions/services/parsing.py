from typing import Any

from ..exceptions import UserDefinitionValidationError

DEFINITION_KINDS = ("glossary", "expert_rule")
MAX_NAME_LENGTH = 200
MAX_DEFINITION_LENGTH = 2000
MAX_DEFINITIONS = 10
CLARIFICATION_STATES = ("confirmed", "dismissed")
# How administrators settled a user's own definition: a shared business term or rule now covers the concept
# (`promoted`), or it stays the user's personal sense (`ignored`). Shared rules carry the business's own thresholds,
# set by its experts; a user's threshold is only a signal of what people ask about.
REVIEW_STATUSES = ("pending", "promoted", "ignored")
MAX_REVIEW_IDS = 200


def _text(item: dict[str, Any], key: str, label: str, max_length: int, required: bool = True) -> str | None:
    value = item.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise UserDefinitionValidationError(f"{label} phải là chuỗi không rỗng.")
    value = value.strip()
    if len(value) > max_length:
        raise UserDefinitionValidationError(f"{label} tối đa {max_length} ký tự.")
    return value or None


def parse_definition(item: Any) -> dict[str, Any]:
    """One definition as `{kind, name, concept, definition}`, trimmed."""
    if not isinstance(item, dict):
        raise UserDefinitionValidationError("Mỗi định nghĩa phải là JSON object.")
    if item.get("kind") not in DEFINITION_KINDS:
        raise UserDefinitionValidationError("Loại định nghĩa phải là glossary hoặc expert_rule.")
    return {
        "kind": item["kind"],
        "name": _text(item, "name", "Tên", MAX_NAME_LENGTH),
        "concept": _text(item, "concept", "Khái niệm", MAX_NAME_LENGTH, required=False),
        "definition": _text(item, "definition", "Định nghĩa", MAX_DEFINITION_LENGTH),
    }


def parse_definitions(items: Any) -> list[dict[str, Any]]:
    """The definitions a user confirms at once; at least one, and one per kind and name."""
    if not isinstance(items, list) or not items:
        raise UserDefinitionValidationError("Cần ít nhất một định nghĩa để xác nhận.")
    if len(items) > MAX_DEFINITIONS:
        raise UserDefinitionValidationError(f"Tối đa {MAX_DEFINITIONS} định nghĩa mỗi lần.")
    parsed: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        definition = parse_definition(item)
        parsed[(definition["kind"], definition["name"].casefold())] = definition
    return list(parsed.values())


def parse_clarification(body: Any) -> tuple[str, list[dict[str, Any]]]:
    """The user's answer to a question's clarifications: `confirmed` with the definitions they chose, or `dismissed`."""
    body = body if isinstance(body, dict) else {}
    state = body.get("state")
    if state not in CLARIFICATION_STATES:
        raise UserDefinitionValidationError("Trạng thái phải là confirmed hoặc dismissed.")
    return state, parse_definitions(body.get("definitions")) if state == "confirmed" else []


def parse_review(body: Any) -> tuple[list[int], str]:
    """An administrator's `{ids, status}` decision on users' definitions."""
    body = body if isinstance(body, dict) else {}
    definition_ids, status = body.get("ids"), body.get("status")
    if status not in REVIEW_STATUSES:
        raise UserDefinitionValidationError("Trạng thái phải là pending, promoted hoặc ignored.")
    valid_ids = isinstance(definition_ids, list) and 0 < len(definition_ids) <= MAX_REVIEW_IDS and all(
        isinstance(item, int) and not isinstance(item, bool) for item in definition_ids
    )
    if not valid_ids:
        raise UserDefinitionValidationError(f"Cần từ 1 đến {MAX_REVIEW_IDS} id định nghĩa.")
    return definition_ids, status
