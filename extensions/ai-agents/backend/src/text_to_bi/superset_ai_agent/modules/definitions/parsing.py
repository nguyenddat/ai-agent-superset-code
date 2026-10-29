from typing import Any

DEFINITION_KINDS = ("glossary", "expert_rule")
MAX_NAME_LENGTH = 200
MAX_DEFINITION_LENGTH = 2000
MAX_DEFINITIONS = 10


class DefinitionError(ValueError):
    """The request body is not a valid definition; the message is safe to show to the user."""


def _text(item: dict[str, Any], key: str, label: str, max_length: int, required: bool = True) -> str | None:
    value = item.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise DefinitionError(f"{label} phải là chuỗi không rỗng.")
    value = value.strip()
    if len(value) > max_length:
        raise DefinitionError(f"{label} tối đa {max_length} ký tự.")
    return value or None


def parse_definition(item: Any) -> dict[str, Any]:
    """One definition as `{kind, name, concept, definition}`, trimmed."""
    if not isinstance(item, dict):
        raise DefinitionError("Mỗi định nghĩa phải là JSON object.")
    if item.get("kind") not in DEFINITION_KINDS:
        raise DefinitionError("Loại định nghĩa phải là glossary hoặc expert_rule.")
    return {
        "kind": item["kind"],
        "name": _text(item, "name", "Tên", MAX_NAME_LENGTH),
        "concept": _text(item, "concept", "Khái niệm", MAX_NAME_LENGTH, required=False),
        "definition": _text(item, "definition", "Định nghĩa", MAX_DEFINITION_LENGTH),
    }


def parse_definitions(items: Any) -> list[dict[str, Any]]:
    """The definitions a user confirms at once; at least one, and one per kind and name."""
    if not isinstance(items, list) or not items:
        raise DefinitionError("Cần ít nhất một định nghĩa để xác nhận.")
    if len(items) > MAX_DEFINITIONS:
        raise DefinitionError(f"Tối đa {MAX_DEFINITIONS} định nghĩa mỗi lần.")
    parsed: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        definition = parse_definition(item)
        parsed[(definition["kind"], definition["name"].casefold())] = definition
    return list(parsed.values())
