from ...common.exceptions import ConflictError, NotFoundError, SelfApprovalError, ValidationError


class GlossaryValidationError(ValidationError):
    """A client-visible validation error that contains no protected metadata."""


class GlossaryConflictError(ConflictError):
    """An optimistic concurrency conflict."""


class GlossarySelfApprovalError(SelfApprovalError):
    """The author of a revision tried to approve it while a second reviewer is required."""

    message = "Người soạn thuật ngữ không thể tự duyệt; cần một quản trị viên khác duyệt."


class GlossaryTermNotFoundError(NotFoundError):
    message = "Glossary term not found."
