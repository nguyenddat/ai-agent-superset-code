from ...common.exceptions import NotFoundError, ValidationError


class ChatSessionNotFoundError(NotFoundError):
    message = "Không tìm thấy cuộc trò chuyện."


class ChatSessionTitleError(ValidationError):
    message = "Tên cuộc trò chuyện phải là chuỗi không rỗng, tối đa 200 ký tự."


class ClarificationNotPendingError(NotFoundError):
    message = "Không có câu hỏi nào đang chờ bạn xác nhận cách hiểu."
