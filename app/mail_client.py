"""MailOps API 邮箱客户端。"""
import time
from dataclasses import dataclass

import httpx

MAILOPS_KEYWORDS = "code,验证码,verification code,trae"


class NoMailboxError(Exception):
    """邮箱池无可用邮箱。"""


class LeaseExpiredError(Exception):
    """lease_token 失效(409)。"""


@dataclass
class ReservedMailbox:
    email: str
    lease_token: str
    lease_expires_at: str = ""


class MailOpsClient:
    def __init__(self, api_key: str, base_url: str = "https://gptmail.passkissyou.online",
                 http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client(timeout=30)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict) -> dict:
        resp = self._http.post(f"{self.base_url}{path}", headers=self._headers, json=payload)
        if resp.status_code == 409:
            raise LeaseExpiredError(resp.text)
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: dict) -> dict:
        resp = self._http.get(f"{self.base_url}{path}", headers=self._headers, params=params)
        if resp.status_code == 409:
            raise LeaseExpiredError(resp.text)
        resp.raise_for_status()
        return resp.json()

    def reserve(self, platform: str, request_id: str, lease_seconds: int) -> ReservedMailbox:
        data = self._post("/api/reuse/v1/mail/reserve", {
            "platform": platform,
            "request_id": request_id,
            "lease_seconds": lease_seconds,
        })
        if not data.get("email"):
            raise NoMailboxError(data.get("reason", "no_available"))
        return ReservedMailbox(
            email=data["email"],
            lease_token=data["lease_token"],
            lease_expires_at=data.get("lease_expires_at", ""),
        )

    def poll_code(self, email: str, lease_token: str) -> str | None:
        data = self._get("/api/mail/code", {
            "email": email,
            "lease_token": lease_token,
            "keyword": MAILOPS_KEYWORDS,
            "limit": 10,
            "folders": "inbox,junk",
        })
        if data.get("found") and data.get("code"):
            return str(data["code"])
        return None

    def wait_for_code(self, email: str, lease_token: str,
                      timeout: int = 180, interval: int = 8) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            code = self.poll_code(email, lease_token)
            if code:
                return code
            time.sleep(interval)
        raise TimeoutError(f"验证码超时({timeout}s): {email}")

    def mark_used(self, email: str, lease_token: str, *, platform: str,
                  login_email: str, status: str = "available", detail: dict | None = None) -> None:
        self._post("/api/reuse/v1/mail/mark-used", {
            "platform": platform,
            "email": email,
            "lease_token": lease_token,
            "login_email": login_email,
            "status": status,
            "detail": detail or {"stage": "registered"},
        })

    def release(self, email: str, lease_token: str, *, platform: str, reason: str) -> None:
        self._post("/api/reuse/v1/mail/release", {
            "platform": platform,
            "email": email,
            "lease_token": lease_token,
            "reason": reason,
        })
