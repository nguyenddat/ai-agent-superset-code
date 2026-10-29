from ...common.exceptions import NotFoundError, ValidationError


class BusinessModelValidationError(ValidationError):
    """A canvas, data layer, business domain or lineage edge that breaks a rule."""


class DataLayerNotFoundError(NotFoundError):
    message = "Data layer not found."


class BusinessDomainNotFoundError(NotFoundError):
    message = "Business domain not found."


class DuplicateDataLayerNameError(ValidationError):
    message = "Tên tầng dữ liệu đã tồn tại."


class DuplicateBusinessDomainNameError(ValidationError):
    message = "Tên nghiệp vụ đã tồn tại."
