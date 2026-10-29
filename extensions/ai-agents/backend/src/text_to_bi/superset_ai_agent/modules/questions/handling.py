from typing import Any

# `pending` is the absence of a handling row; it is accepted on write so an administrator can undo a decision.
HANDLING_STATUSES = ("pending", "to_create", "created", "ignored")
MAX_NOTE_LENGTH = 1000


class HandlingError(ValueError):
    """The request body is not a valid handling decision; the message is safe to show to the user."""


def parse_handling(body: Any) -> tuple[str, str | None]:
    """Validate a handling decision and return its status and trimmed note."""
    if not isinstance(body, dict):
        raise HandlingError("Nội dung yêu cầu phải là JSON object.")
    status = body.get("status")
    if status not in HANDLING_STATUSES:
        raise HandlingError("Trạng thái xử lý phải là pending, to_create, created hoặc ignored.")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise HandlingError("Ghi chú phải là chuỗi.")
    note = (note or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise HandlingError(f"Ghi chú tối đa {MAX_NOTE_LENGTH} ký tự.")
    return status, note or None


def count_by_handling(statuses: list[str | None]) -> dict[str, int]:
    """Count questions per handling status; a question with no handling row counts as `pending`."""
    counts = dict.fromkeys(HANDLING_STATUSES, 0)
    for status in statuses:
        counts[status if status in counts else "pending"] += 1
    return counts
