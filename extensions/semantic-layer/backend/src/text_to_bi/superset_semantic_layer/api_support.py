from collections.abc import Callable

from flask import current_app
from superset import security_manager


def second_reviewer_required() -> bool:
    """Whether a proposal's author must leave its approval to another administrator.

    Off by default so a single administrator can approve their own work; a deployment with several reviewers
    sets TEXT_TO_BI_REQUIRE_SECOND_REVIEWER = True in superset_config.
    """
    return bool(current_app.config.get("TEXT_TO_BI_REQUIRE_SECOND_REVIEWER", False))


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
