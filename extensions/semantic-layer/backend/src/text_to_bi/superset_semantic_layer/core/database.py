import logging
from functools import wraps

from superset import db

from ..common.exceptions import SemanticLayerError

logger = logging.getLogger(__name__)


def handle_errors(method):
    """Answer a Semantic Layer error with its status and message, discarding the half-done transaction.

    It sits directly above the route function, inside rollback_on_error and Superset's @safe, which would answer 500.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except SemanticLayerError as error:
            db.session.rollback()
            return self.response(error.status, message=str(error))

    return wrapper


def rollback_on_error(method):
    """Log an unexpected failure, discard the half-done transaction and answer with a plain 500."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            logger.exception("%s failed", method.__name__)
            db.session.rollback()
            return self.response_500(message="Could not save the change.")

    return wrapper
