from ...common.exceptions import NotFoundError


class DatasetNotFoundError(NotFoundError):
    message = "Dataset not found."


class DatabaseNotFoundError(NotFoundError):
    message = "Database not found."
