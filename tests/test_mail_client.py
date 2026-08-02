import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pytest

from app.mail_client import MailOpsClient, NoMailboxError


def _client(handler):
    transport = httpx.MockTransport(handler)
    return MailOpsClient(api_key="mak_test", base_url="https://mock.local",
                         http_client=httpx.Client(transport=transport))


def test_reserve_ok():
    def handler(request):
        assert request.url.path == "/api/reuse/v1/mail/reserve"
        assert request.headers["authorization"] == "Bearer mak_test"
        return httpx.Response(200, json={
            "ok": True, "email": "user1@outlook.com",
            "lease_token": "lease_abc", "lease_expires_at": "2026-08-02T10:00:00Z",
        })

    c = _client(handler)
    r = c.reserve(platform="trae", request_id="b1-w1-a1", lease_seconds=1800)
    assert r.email == "user1@outlook.com"
    assert r.lease_token == "lease_abc"


def test_reserve_no_available():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "email": "",
                                         "reason": "no_available"})

    c = _client(handler)
    with pytest.raises(NoMailboxError):
        c.reserve(platform="trae", request_id="b1-w1-a1", lease_seconds=1800)


def test_poll_code_found():
    def handler(request):
        params = request.url.params
        assert params["email"] == "user1@outlook.com"
        assert params["lease_token"] == "lease_abc"
        return httpx.Response(200, json={"ok": True, "found": True, "code": "123456"})

    c = _client(handler)
    code = c.poll_code("user1@outlook.com", "lease_abc")
    assert code == "123456"


def test_poll_code_not_found():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "found": False})

    c = _client(handler)
    assert c.poll_code("user1@outlook.com", "lease_abc") is None


def test_mark_used_and_release():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    c = _client(handler)
    c.mark_used("user1@outlook.com", "lease_abc", platform="trae",
                login_email="user1@outlook.com")
    c.release("user1@outlook.com", "lease_abc", platform="trae", reason="test")
    assert calls == ["/api/reuse/v1/mail/mark-used", "/api/reuse/v1/mail/release"]


import pytest


@pytest.mark.asyncio
async def test_async_client_reserve_and_poll():
    from app.mail_client import AsyncMailOpsClient

    def handler(request):
        if request.url.path == "/api/reuse/v1/mail/reserve":
            return httpx.Response(200, json={"ok": True, "email": "u@outlook.com",
                                             "lease_token": "lt1"})
        return httpx.Response(200, json={"ok": True, "found": True, "code": "654321"})

    c = AsyncMailOpsClient(api_key="mak_test", base_url="https://mock.local",
                           http_client=httpx.AsyncClient(
                               transport=httpx.MockTransport(handler)))
    mb = await c.reserve("trae", "b1-w1-a1", 1800)
    assert mb.email == "u@outlook.com"
    code = await c.poll_code("u@outlook.com", "lt1")
    assert code == "654321"
