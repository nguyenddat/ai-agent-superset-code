from ...common.exceptions import ConflictError, NotFoundError, SelfApprovalError, ValidationError


class ExpertRuleValidationError(ValidationError):
    """Safe, client-visible validation error."""


class ExpertRuleConflictError(ConflictError):
    """Optimistic revision conflict."""

    message = "The expert rule changed; refresh and retry."


class ExpertRuleSelfApprovalError(SelfApprovalError):
    """The author of a revision tried to approve it; a second administrator must."""

    message = "Người soạn rule không thể tự duyệt; cần một quản trị viên khác duyệt."


class ExpertRuleNotFoundError(NotFoundError):
    message = "Expert rule not found."
