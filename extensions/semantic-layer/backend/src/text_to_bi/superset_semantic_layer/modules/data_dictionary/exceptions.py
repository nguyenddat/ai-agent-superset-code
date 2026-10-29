from ...common.exceptions import ConflictError, ServiceUnavailableError, ValidationError


class DataDictionaryValidationError(ValidationError):
    """Dictionary metadata, time semantics or an indicator model that breaks a rule."""


class NoColumnsToDescribeError(ValidationError):
    message = "Dataset has no columns to describe."


class ReferencedColumnMissingError(ValidationError):
    message = "Referenced column no longer exists."


class NotIndicatorCatalogError(ValidationError):
    message = "The dataset is not declared an indicator catalog."


class SuggestionInProgressError(ConflictError):
    message = "Dataset này đang được AI gợi ý, vui lòng đợi hoàn tất."


class AutoFillUnavailableError(ServiceUnavailableError):
    message = "AI AutoFill chưa sẵn sàng."
