from ...common.exceptions import NotAuthorizedError


class DashboardAccessError(NotAuthorizedError):
    message = "Dashboard không tồn tại hoặc bạn không có quyền xem."
