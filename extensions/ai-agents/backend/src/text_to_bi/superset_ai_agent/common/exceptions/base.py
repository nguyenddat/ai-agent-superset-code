class AgentError(Exception):
    """A request the AI Agent refuses, answered with `status` and a message safe to show the client.

    The classes here are abstract: a module raises its own subclass, such as ChatSessionNotFoundError, which names
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


class ValidationError(AgentError, ValueError):
    """The submitted content breaks a rule; nothing was saved. It stays a ValueError, as validators raised before."""

    abstract = True
    status = 400
    message = "Dữ liệu gửi lên không hợp lệ."


class NotAuthorizedError(AgentError):
    """The caller lacks the role or the Superset permission the request needs."""

    abstract = True
    status = 403
    message = "Không có quyền thực hiện thao tác này."


class NotFoundError(AgentError):
    """The record the request names does not exist, or belongs to another user."""

    abstract = True
    status = 404
    message = "Không tìm thấy dữ liệu."


class ServiceUnavailableError(AgentError):
    """A service the request depends on, such as the language model or the Semantic Layer, cannot be reached."""

    abstract = True
    status = 503
    message = "Dịch vụ tạm thời không sẵn sàng."
