from ...common.exceptions import NotFoundError, ValidationError


class UserDefinitionValidationError(ValidationError):
    """The request body is not a valid definition; the message is safe to show to the user."""


class UserDefinitionNotFoundError(NotFoundError):
    message = "Không tìm thấy định nghĩa."


class DashboardIdRequiredError(ValidationError):
    message = "Cần dashboard_id."
