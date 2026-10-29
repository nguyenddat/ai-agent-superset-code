from ...common.exceptions import NotAuthorizedError, ValidationError


class GoalError(ValidationError):
    """The goal does not fit the schema graph; the message says what to change."""


class NoJoinPathError(ValidationError):
    """Some needed table is not reachable from the root through approved relationships."""

    message = "No approved relationships connect every needed table."

    def __init__(self, unreachable: list[int]) -> None:
        super().__init__()
        self.unreachable = unreachable


class AnalysisLabAdminRequiredError(NotAuthorizedError):
    message = "Chỉ quản trị viên dùng được phòng thử phân tích."


class DatabaseIdRequiredError(ValidationError):
    message = "Cần database_id."
