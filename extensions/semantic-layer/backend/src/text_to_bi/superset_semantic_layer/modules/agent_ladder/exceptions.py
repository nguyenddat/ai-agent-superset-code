from ...common.exceptions import ConflictError, NotFoundError, TooManyRequestsError, ValidationError


class AgentLadderValidationError(ValidationError):
    """A metric draft, a dataset proposal or its review that breaks a rule."""


class AggregateDatasetRequiredError(ValidationError):
    message = "AI Agent chỉ tạo metric trên dataset tổng hợp (aggregate)."


class ProposalAlreadyReviewedError(ValidationError):
    message = "Đề xuất này đã được xử lý."


class ProposedDatasetCreationError(ValidationError):
    message = "Superset không chạy được câu SQL để đọc các cột của dataset."


class AgentMetricRevokedError(ConflictError):
    message = "Một metric cùng công thức đã bị quản trị viên thu hồi."


class AgentMetricPendingError(ConflictError):
    message = "Một metric cùng công thức đang chờ quản trị viên xử lý."


class TooManyPendingAgentMetricsError(TooManyRequestsError):
    message = "Dataset này có quá nhiều metric AI Agent đang chờ duyệt."


class TooManyPendingProposalsError(TooManyRequestsError):
    message = "Đã có quá nhiều đề xuất dataset đang chờ duyệt."


class DatasetProposalNotFoundError(NotFoundError):
    message = "Dataset proposal not found."
