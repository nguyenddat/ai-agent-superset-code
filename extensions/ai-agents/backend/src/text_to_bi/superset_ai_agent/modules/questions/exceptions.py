from ...common.exceptions import NotFoundError, ValidationError


class QuestionHandlingValidationError(ValidationError):
    """The request is not a valid handling decision or review filter; the message is safe to show to the user."""


class QuestionNotFoundError(NotFoundError):
    message = "Không tìm thấy câu hỏi."
