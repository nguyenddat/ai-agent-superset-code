from ...common.exceptions import (
    ConflictError,
    NotAuthorizedError,
    NotFoundError,
    SelfApprovalError,
    ValidationError,
)


class SemanticQueryError(ValidationError):
    """Raised when a semantic query is outside the supported safe contract."""


class MetricContractValidationError(ValidationError):
    """A metric contract, its review or its business definition breaks a rule."""


class RelationshipValidationError(ValidationError):
    """A relationship between datasets, or its contract, breaks a rule."""


class MetricNotFoundError(NotFoundError):
    message = "Metric not found in this dataset."


class MetricContractNotFoundError(NotFoundError):
    message = "Metric contract not found in this dataset."


class ForeignKeyColumnNotFoundError(NotFoundError):
    message = "Foreign-key dictionary column not found in this dataset."


class RelationshipContractNotFoundError(NotFoundError):
    message = "Relationship contract not found for this foreign key."


class RelationshipCandidateRequiredError(NotFoundError):
    message = "Create a candidate contract before checking the data."


class ApprovedMetricContractRequiredError(NotAuthorizedError):
    message = "A current approved metric contract is required."


class ApprovedMetricDatasetRequiredError(NotAuthorizedError):
    message = "A dataset with an approved metric contract is required."


class MetricSelfApprovalError(SelfApprovalError):
    message = "Người đề xuất không thể tự duyệt; cần một quản trị viên khác duyệt."


class MetricExecutionDeniedError(NotAuthorizedError):
    message = "Superset denied metric execution."


class ApprovedContractExistsError(ConflictError):
    message = "Revoke the current approved contract before creating another candidate."
