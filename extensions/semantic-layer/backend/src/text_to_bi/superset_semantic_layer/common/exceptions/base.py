class SemanticLayerError(Exception):
    """A request the Semantic Layer refuses, answered with `status` and a message safe to show the client.

    The classes here are abstract: a module raises its own subclass, such as GlossaryTermNotFoundError, which names
    what failed and carries a default `message`; a raise may pass a more precise one. A route lets the error propagate
    and `handle_errors` answers it.
    """

    abstract = True
    status = 400
    message = "Yêu cầu không hợp lệ."

    def __new__(cls, *args, **kwargs):
        if cls.__dict__.get("abstract", False):
            raise TypeError(f"{cls.__name__} is abstract; raise a module's own subclass.")
        return super().__new__(cls, *args, **kwargs)

    def __init__(self, message: str | None = None) -> None:
        super().__init__(self.message if message is None else message)


class ValidationError(SemanticLayerError, ValueError):
    """The submitted content breaks a rule; nothing was saved. It stays a ValueError, as validators raised before."""

    abstract = True
    status = 400
    message = "Dữ liệu gửi lên không hợp lệ."


class NotAuthorizedError(SemanticLayerError):
    """The caller lacks the role or the Superset permission the request needs."""

    abstract = True
    status = 403
    message = "Không có quyền thực hiện thao tác này."


class SelfApprovalError(NotAuthorizedError):
    """The author of a revision tried to approve it while a second reviewer is required."""

    abstract = True
    message = "Người soạn không thể tự duyệt; cần một quản trị viên khác duyệt."


class NotFoundError(SemanticLayerError):
    """The record the request names does not exist."""

    abstract = True
    status = 404
    message = "Không tìm thấy dữ liệu."


class ConflictError(SemanticLayerError):
    """The record is not in the state the request expects: someone changed it first, or it is still busy."""

    abstract = True
    status = 409
    message = "Dữ liệu đã thay đổi; tải lại rồi thử lại."


class TooManyRequestsError(SemanticLayerError):
    """Too many requests of this kind are already waiting."""

    abstract = True
    status = 429
    message = "Có quá nhiều yêu cầu đang chờ xử lý."


class ServiceUnavailableError(SemanticLayerError):
    """A service the request depends on, such as the language model, cannot be reached or is not configured."""

    abstract = True
    status = 503
    message = "Dịch vụ tạm thời không sẵn sàng."
