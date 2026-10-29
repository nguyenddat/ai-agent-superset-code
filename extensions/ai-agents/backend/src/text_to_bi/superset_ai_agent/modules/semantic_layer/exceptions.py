from ...common.exceptions import ServiceUnavailableError, ValidationError


class SemanticLayerUnavailableError(ServiceUnavailableError):
    """The Semantic Layer could not be read: unreachable, the user lacks access, or it answered with an error."""

    message = "Không kết nối được tới Semantic Layer."


class SemanticLayerRefusedError(ValidationError):
    """The Semantic Layer refused or failed a request the agent made as the user; the message is its own."""

    message = "Semantic Layer từ chối yêu cầu."
