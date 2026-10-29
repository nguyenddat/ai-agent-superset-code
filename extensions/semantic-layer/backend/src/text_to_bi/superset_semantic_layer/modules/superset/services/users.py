from collections.abc import Callable
from typing import Any

from superset import security_manager

from ..dependencies import superset_user_repository


def active_users() -> list[Any]:
    """Active Superset users, by username."""
    return superset_user_repository().active()


def user_names() -> Callable[[int | None], str | None]:
    """A per-request lookup from user ID to display name: full name, else username."""
    names: dict[int, str | None] = {}

    def user_name(user_id: int | None) -> str | None:
        if user_id is None:
            return None
        if user_id not in names:
            user = security_manager.get_user_by_id(user_id)
            names[user_id] = (user.get_full_name().strip() or user.username) if user else None
        return names[user_id]

    return user_name
