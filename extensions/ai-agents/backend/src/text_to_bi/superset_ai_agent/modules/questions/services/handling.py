from typing import Any

from ..exceptions import QuestionHandlingValidationError

# `pending` is the absence of a handling row; it is accepted on write so an administrator can undo a decision.
HANDLING_STATUSES = ("pending", "to_create", "created", "ignored")
MISSING_KINDS = ("glossary", "metric", "expert_rule")
MAX_NOTE_LENGTH = 1000


def parse_handling(body: Any) -> tuple[str, str | None]:
    """Validate a handling decision and return its status and trimmed note."""
    if not isinstance(body, dict):
        raise QuestionHandlingValidationError("Nội dung yêu cầu phải là JSON object.")
    status = body.get("status")
    if status not in HANDLING_STATUSES:
        raise QuestionHandlingValidationError("Trạng thái xử lý phải là pending, to_create, created hoặc ignored.")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise QuestionHandlingValidationError("Ghi chú phải là chuỗi.")
    note = (note or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise QuestionHandlingValidationError(f"Ghi chú tối đa {MAX_NOTE_LENGTH} ký tự.")
    return status, note or None


def parse_review_filters(handling: str, missing: str | None) -> tuple[str, str | None]:
    """The review list's `?handling=` (a handling status or `all`) and `?missing=` (a missing kind) filters."""
    if handling not in ("all", *HANDLING_STATUSES):
        raise QuestionHandlingValidationError("Bộ lọc xử lý không hợp lệ.")
    if missing not in (None, *MISSING_KINDS):
        raise QuestionHandlingValidationError("Bộ lọc phần thiếu không hợp lệ.")
    return handling, missing


def count_by_handling(statuses: list[str | None]) -> dict[str, int]:
    """Count questions per handling status; a question with no handling row counts as `pending`."""
    counts = dict.fromkeys(HANDLING_STATUSES, 0)
    for status in statuses:
        counts[status if status in counts else "pending"] += 1
    return counts
