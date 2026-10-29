from flask import request
from flask_login import current_user


def is_admin() -> bool:
    return bool(current_user and current_user.is_authenticated and any(
        role.name == "Admin" for role in getattr(current_user, "roles", [])
    ))


def valid_csrf() -> bool:
    from flask_wtf.csrf import validate_csrf
    from wtforms import ValidationError

    try:
        validate_csrf(request.headers.get("X-CSRFToken"))
    except ValidationError:
        return False
    return True
