import threading
import time
from collections.abc import Callable
from typing import Any

import requests

from ....core.config import settings
from ..exceptions import SemanticLayerRefusedError, SemanticLayerUnavailableError

SEMANTIC_LAYER_API = "/extensions/text-to-bi/superset-semantic-layer/semantic-layer"
EXPERT_RULES_API = "/extensions/text-to-bi/superset-semantic-layer/expert-rules/expert-rules"
REQUEST_TIMEOUT_SECONDS = 20
# Approved content changes rarely; a user's follow-up questions reuse what was read a moment ago.
CACHE_SECONDS = 60

_cache_lock = threading.Lock()


def internal_superset_url() -> str:
    """Superset as seen from inside its own container; the Compose service listens on 8088."""
    return settings.TEXT_TO_BI_SUPERSET_INTERNAL_URL.rstrip("/")


def get_json(path: str, cookie_header: str) -> dict[str, Any]:
    """GET as the asking user; raises SemanticLayerUnavailableError when the answer is not a 200."""
    try:
        response = requests.get(
            internal_superset_url() + path,
            headers={"Cookie": cookie_header, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise SemanticLayerUnavailableError() from error
    if response.status_code in (401, 403):
        raise SemanticLayerUnavailableError("Bạn chưa có quyền đọc dữ liệu quản trị nghiệp vụ của Semantic Layer.")
    if response.status_code != 200:
        raise SemanticLayerUnavailableError(f"Semantic Layer trả về lỗi {response.status_code}.")
    return response.json()


def post_json(path: str, body: dict[str, Any], cookie_header: str, csrf_token: str, action: str) -> dict[str, Any]:
    """POST as the asking user to `action` (\"chạy truy vấn\"); a refusal carries the Semantic Layer's own message."""
    try:
        response = requests.post(
            internal_superset_url() + path,
            json=body,
            headers={"Cookie": cookie_header, "X-CSRFToken": csrf_token, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise SemanticLayerRefusedError(f"Không kết nối được tới Semantic Layer để {action}.") from error
    answer = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
    if response.status_code not in (200, 201):
        message = answer.get("message") if isinstance(answer.get("message"), str) else None
        raise SemanticLayerRefusedError(message or f"Semantic Layer trả về lỗi {response.status_code} khi {action}.")
    return answer


def cached(store: dict, key: Any, load: Callable[[], Any]) -> Any:
    """What `load` returns for `key`, read again after `CACHE_SECONDS`; keyed by user because access differs."""
    now = time.monotonic()
    with _cache_lock:
        entry = store.get(key)
    if entry and now - entry[0] < CACHE_SECONDS:
        return entry[1]
    value = load()
    with _cache_lock:
        store[key] = (now, value)
    return value
