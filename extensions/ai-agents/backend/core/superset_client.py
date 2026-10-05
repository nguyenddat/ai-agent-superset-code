import base64
import binascii
import json
import threading
import time
from typing import Any

import requests

from .settings import config


class SupersetClient:
    def __init__(self, base_url: str, username: str, password: str, provider: str = "db"):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.provider = provider
        self.session = requests.Session()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.RLock()

    @staticmethod
    def _token_expiry(token: str) -> float:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        except (IndexError, KeyError, ValueError, TypeError, binascii.Error):
            return 0.0

    def _set_tokens(self, payload: dict[str, Any], keep_refresh: bool = False) -> None:
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("Superset did not return an access token")
        self._access_token = token
        self._refresh_token = payload.get("refresh_token") or (self._refresh_token if keep_refresh else None)
        self._expires_at = self._token_expiry(token)

    def _login(self) -> None:
        response = self.session.post(
            f"{self.base_url}/api/v1/security/login",
            json={"username": self.username, "password": self.password, "provider": self.provider, "refresh": True},
            timeout=30,
        )
        response.raise_for_status()
        self._set_tokens(response.json())

    def _refresh(self) -> None:
        if not self._refresh_token:
            self._login()
            return
        response = self.session.post(
            f"{self.base_url}/api/v1/security/refresh",
            headers={"Authorization": f"Bearer {self._refresh_token}"},
            timeout=30,
        )
        if response.status_code in (401, 422):
            self._login()
            return
        response.raise_for_status()
        self._set_tokens(response.json(), keep_refresh=True)

    def _get_access_token(self) -> str:
        with self._lock:
            if not self._access_token:
                self._login()
            elif self._expires_at and time.time() >= self._expires_at - 30:
                self._refresh()
            return self._access_token

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        token = self._get_access_token()
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {token}"}
        response = self.session.get(url, headers=headers, **kwargs)
        if response.status_code in (401, 422):
            with self._lock:
                if token == self._access_token:
                    self._refresh()
                token = self._access_token
            headers["Authorization"] = f"Bearer {token}"
            response = self.session.get(url, headers=headers, **kwargs)
        return response


superset_client = SupersetClient(config.superset_base_url, config.superset_username, config.superset_password)
