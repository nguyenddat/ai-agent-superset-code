from ..common.exceptions import NotAuthorizedError, NotFoundError, ValidationError


class AdminRequiredError(NotAuthorizedError):
    message = "Admin access required."


class DatasetAccessError(NotAuthorizedError):
    message = "Dataset and database access required."


class CsrfTokenError(NotAuthorizedError):
    message = "CSRF token không hợp lệ."


class DatasetNotFoundError(NotFoundError):
    message = "Dataset not found."


class DatabaseNotFoundError(NotFoundError):
    message = "Database not found."


class DatasetIdRequiredError(ValidationError):
    message = "dataset_id is required."


class DatabaseIdRequiredError(ValidationError):
    message = "database_id is required."


class RequestBodyError(ValidationError):
    message = "Request body must be a JSON object."
