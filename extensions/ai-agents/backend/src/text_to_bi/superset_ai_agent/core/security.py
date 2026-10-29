from functools import wraps

from flask import request
from flask_login import current_user
from flask_wtf.csrf import validate_csrf
from wtforms import ValidationError

from .exceptions import AdminRequiredError, CsrfTokenError


def is_admin() -> bool:
    return bool(
        getattr(current_user, "is_authenticated", False)
        and any(role.name == "Admin" for role in getattr(current_user, "roles", []))
    )


def require_admin() -> None:
    if not is_admin():
        raise AdminRequiredError()


def csrf_protected(method):
    """Reject a state-changing request that does not carry a valid CSRF token."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            error = CsrfTokenError()
            return self.response(error.status, message=str(error))
        return method(self, *args, **kwargs)

    return wrapper
