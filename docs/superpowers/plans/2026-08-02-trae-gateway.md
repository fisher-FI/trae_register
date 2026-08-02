# Trae 反代网关(阶段二)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Trae 聊天能力包装成 OpenAI 兼容 API(`/v1/chat/completions` + `/v1/models`),账号池轮询调度、健康检查、失败切换。

**Architecture:** 在阶段一 FastAPI 单体内新增 `app/gateway/` 包;`trae_client` 封装真实聊天协议(协议数据来自接口侦察结果,端点/字段配置化);`account_pool` 从 SQLite 账号库加载凭据做轮询与健康检查;`adapter` 完成 OpenAI 请求/响应/SSE 双向转换。

**Tech Stack:** Python 3.12, FastAPI, httpx/curl_cffi, asyncio

**前置:** 阶段一完成且至少 1 个账号注册成功(含凭据入库)。

**设计文档:** `docs/superpowers/specs/2026-08-02-trae-register-design.md`

---

## 文件结构

```
trae_register/
├── app/
│   ├── gateway/
│   │   ├── __init__.py
│   │   ├── recon.py           # 接口侦察:Playwright 拦截聊天请求,产出协议 JSON
│   │   ├── trae_client.py     # Trae 聊天客户端(协议配置驱动)
│   │   ├── account_pool.py    # 账号轮询/健康检查
│   │   └── adapter.py         # OpenAI 兼容转换(请求/响应/SSE)
│   └── api.py                 # 修改:挂载 /v1/* 网关路由 + 网关管理接口
├── logs/chat_protocol.json    # 侦察产物(运行时生成,提交样例 schema)
├── tests/
│   ├── test_recon.py          # 侦察产物 schema 校验
│   ├── test_trae_client.py    # mock 协议响应
│   ├── test_account_pool.py
│   └── test_adapter.py
```

---

### Task 1: 聊天接口侦察

**Files:**
- Create: `app/gateway/__init__.py`
- Create: `app/gateway/recon.py`
- Test: `tests/test_recon.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_recon.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gateway.recon import PROTOCOL_SCHEMA


def test_schema_shape():
    # 侦察产物 schema 必须定义聊天端点、认证、请求体、响应体字段
    assert "chat_endpoint" in PROTOCOL_SCHEMA
    assert "auth" in PROTOCOL_SCHEMA
    assert "request_body" in PROTOCOL_SCHEMA
    assert "response_format" in PROTOCOL_SCHEMA


def test_protocol_json_valid(tmp_path):
    # 样例协议文件必须能解析且符合 schema 关键字段
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({
        "chat_endpoint": "https://api.trae.ai/v1/chat",
        "auth": {"type": "cookie", "cookie_name": "session"},
        "request_body": {"messages": "list", "model": "str", "stream": "bool"},
        "response_format": "sse",
    }), encoding="utf-8")
    data = json.loads(sample.read_text(encoding="utf-8"))
    for key in ("chat_endpoint", "auth", "request_body", "response_format"):
        assert key in data
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_recon.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现侦察脚本**

创建 `app/gateway/__init__.py`(空文件)。

创建 `app/gateway/recon.py`:

```python
"""聊天接口侦察:用已注册账号登录 trae.ai,发一条消息并拦截聊天请求,产出协议 JSON。

用法:
    python -m app.gateway.recon --email a@b.com --password pw --request-id recon-001
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent.parent
OUT = BASE_DIR / "logs" / "chat_protocol.json"

# 侦察产物 schema(字段说明,供 trae_client 消费)
PROTOCOL_SCHEMA = {
    "chat_endpoint": "聊天请求 URL(从拦截中识别,含 method)",
    "auth": {"type": "cookie|header", "cookie_name": "", "header_name": ""},
    "request_body": {"messages": "list", "model": "str", "stream": "bool"},
    "response_format": "sse|json",
}


async def recon(email: str, password: str, request_id: str, headless: bool = True) -> dict:
    protocol = {"schema": PROTOCOL_SCHEMA, "captured_at": time.time(),
                "request_id": request_id}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        # 1) 登录
        await page.goto("https://www.trae.ai/login", timeout=60000)
        await page.get_by_role("textbox", name="Email").fill(email)
        await page.get_by_role("textbox", name="Password").fill(password)
        await page.get_by_role("button", name="Log in").click()
        await page.wait_for_url("**/ide**", timeout=60000)

        # 2) 拦截聊天请求
        captured = []

        async def _capture(route):
            req = route.request
            url = req.url
            # 过滤静态资源/遥测,只留疑似聊天接口
            if any(skip in url for skip in (".js", ".css", ".png", "analytics",
                                            "sentry", "metrics")):
                await route.continue_()
                return
            captured.append({
                "ts": time.time(),
                "method": req.method,
                "url": url,
                "headers": dict(req.headers),
                "post_data": req.post_data,
            })
            await route.continue_()

        await ctx.route("**/*", _capture)

        # 3) 发一条消息触发聊天请求
        await page.wait_for_timeout(3000)
        try:
            editor = page.locator("textarea, [contenteditable='true']").first
            await editor.click()
            await editor.fill("Hello, reply with OK only.")
            await editor.press("Enter")
            await page.wait_for_timeout(15000)  # 等流式响应
        except Exception as e:  # noqa: BLE001
            protocol["recon_error"] = f"{type(e).__name__}: {e}"
            await page.screenshot(path=str(BASE_DIR / "screenshots" / f"{request_id}-recon.png"))
            await browser.close()
            return protocol

        # 4) 识别聊天端点(按 body 特征:含 messages / stream 字段)
        for c in captured:
            body = c.get("post_data") or ""
            if "messages" in body and ("stream" in body or "model" in body):
                protocol["chat_endpoint"] = c["url"]
                protocol["method"] = c["method"]
                protocol["request_body"] = json.loads(body) if body else {}
                protocol["auth"] = {
                    "type": "cookie",
                    "cookie_name": "session",
                    "sample_headers": {k: v for k, v in c["headers"].items()
                                       if k.lower() in ("authorization", "x-",
                                                        "cookie")},
                }
                protocol["response_format"] = "sse" if "stream" in body else "json"
                break

        await browser.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    return protocol


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--request-id", default="recon-001")
    args = ap.parse_args()
    result = asyncio.run(recon(args.email, args.password, args.request_id))
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_recon.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 真实侦察**

Run(用阶段一注册成功的账号):

```bash
python -m app.gateway.recon --email <已注册邮箱> --password <密码> --request-id recon-001
```

Expected: `logs/chat_protocol.json` 生成,含 `chat_endpoint`、`request_body` 样例、auth 信息。
若 `recon_error` 出现,按截图校准选择器后重跑。

- [ ] **Step 6: 提交**

```bash
git add app/gateway/ tests/test_recon.py
git commit -m "feat: 聊天接口侦察(recon)脚本,产出协议 JSON"
```

---

### Task 2: Trae 聊天客户端

**Files:**
- Create: `app/gateway/trae_client.py`
- Test: `tests/test_trae_client.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_trae_client.py`(mock 协议,不触网):

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pytest

from app.gateway.trae_client import TraeClient, build_chat_request

PROTOCOL = {
    "chat_endpoint": "https://api.trae.test/v1/chat",
    "method": "POST",
    "auth": {"type": "cookie", "cookie_name": "session"},
    "request_body": {"messages": "list", "model": "str", "stream": "bool"},
    "response_format": "sse",
}


def test_build_chat_request_maps_fields():
    body = build_chat_request(PROTOCOL, messages=[{"role": "user", "content": "hi"}],
                              model="trae-default", stream=False)
    assert body["messages"][0]["content"] == "hi"
    assert body["model"] == "trae-default"
    assert body["stream"] is False


def test_client_sends_cookie_and_parses_sse():
    sse_data = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'

    def handler(request):
        assert request.url == "https://api.trae.test/v1/chat"
        assert request.headers["cookie"] == "session=abc"
        return httpx.Response(200, content=sse_data,
                              headers={"content-type": "text/event-stream"})

    client = TraeClient(PROTOCOL, cookie="session=abc",
                        http=httpx.Client(transport=httpx.MockTransport(handler)))
    chunks = list(client.stream_chat(messages=[{"role": "user", "content": "hi"}],
                                     model="trae-default"))
    assert chunks == [{"choices": [{"delta": {"content": "hi"}}]}]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_trae_client.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现**

创建 `app/gateway/trae_client.py`:

```python
"""Trae 聊天客户端:协议配置驱动(协议来自 recon 侦察结果)。"""
import json
from typing import Any

import httpx


def build_chat_request(protocol: dict, *, messages: list[dict], model: str,
                       stream: bool, extra: dict | None = None) -> dict:
    """按协议 schema 构造聊天请求体。"""
    body = {
        "messages": messages,
        "model": model,
        "stream": stream,
    }
    if extra:
        body.update(extra)
    return body


def parse_sse(line: str) -> dict | None:
    """解析单行 SSE。返回事件 JSON;`[DONE]` 返回 None。"""
    line = line.strip()
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if payload == "[DONE]":
        return None
    return json.loads(payload)


class TraeError(Exception):
    pass


class TraeClient:
    def __init__(self, protocol: dict, cookie: str = "",
                 http: httpx.Client | None = None):
        self.protocol = protocol
        self.cookie = cookie
        self._http = http or httpx.Client(timeout=60)

    def _headers(self) -> dict:
        auth = self.protocol.get("auth", {})
        if auth.get("type") == "cookie":
            return {"cookie": self.cookie or auth.get("cookie_name", "session"),
                    "content-type": "application/json"}
        name = auth.get("header_name", "authorization")
        return {name: self.cookie, "content-type": "application/json"}

    def stream_chat(self, *, messages: list[dict], model: str,
                    stream: bool = True, extra: dict | None = None) -> list[dict]:
        """发起聊天请求并解析流式响应,返回事件列表。"""
        body = build_chat_request(self.protocol, messages=messages, model=model,
                                  stream=stream, extra=extra)
        resp = self._http.post(self.protocol["chat_endpoint"],
                               headers=self._headers(), json=body)
        if resp.status_code != 200:
            raise TraeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        events: list[dict] = []
        for line in resp.text.splitlines():
            ev = parse_sse(line)
            if ev is not None:
                events.append(ev)
        return events
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_trae_client.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add app/gateway/trae_client.py tests/test_trae_client.py
git commit -m "feat: Trae 聊天客户端(协议配置驱动,SSE 解析)"
```

---

### Task 3: 账号池

**Files:**
- Create: `app/gateway/account_pool.py`
- Test: `tests/test_account_pool.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_account_pool.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.gateway.account_pool import AccountPool


class FakeStore:
    def __init__(self, accounts):
        self.accounts = accounts

    def list_healthy_accounts(self):
        return [dict(a) for a in self.accounts]

    def update_account_health(self, email, health):
        for a in self.accounts:
            if a["email"] == email:
                a["health_status"] = health


def test_round_robin_and_failover():
    store = FakeStore([
        {"email": "a@b.com", "cookie": "c1", "access_token": "t1"},
        {"email": "c@d.com", "cookie": "c2", "access_token": "t2"},
    ])
    pool = AccountPool(store, fail_threshold=1, cooldown_seconds=0)
    pool.reload()

    # 轮询:依次返回 a, c, a, c
    assert pool.next().email == "a@b.com"
    assert pool.next().email == "c@d.com"
    assert pool.next().email == "a@b.com"

    # a 失败一次(阈值 1)→ 标记不健康,后续只返回 c
    a = pool.next()
    pool.report_failure(a.email)
    assert pool.next().email == "c@d.com"
    assert store.accounts[0]["health_status"] == "unhealthy"


def test_no_accounts_raises():
    pool = AccountPool(FakeStore([]), fail_threshold=2, cooldown_seconds=0)
    pool.reload()
    with pytest.raises(RuntimeError):
        pool.next()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_account_pool.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现**

创建 `app/gateway/account_pool.py`:

```python
"""账号池:round-robin 轮询、失败切换、健康状态管理。"""
import time
from dataclasses import dataclass


@dataclass
class AccountSlot:
    email: str
    cookie: str
    access_token: str
    refresh_token: str
    failures: int = 0
    unhealthy_at: float = 0.0


class AccountPool:
    def __init__(self, store, fail_threshold: int = 3,
                 cooldown_seconds: int = 300):
        self.store = store
        self.fail_threshold = fail_threshold
        self.cooldown_seconds = cooldown_seconds
        self._slots: list[AccountSlot] = []
        self._cursor = 0

    def reload(self) -> None:
        accounts = self.store.list_healthy_accounts()
        by_email = {s.email: s for s in self._slots}
        self._slots = []
        for a in accounts:
            old = by_email.get(a["email"])
            self._slots.append(AccountSlot(
                email=a["email"],
                cookie=a.get("cookie", ""),
                access_token=a.get("access_token", ""),
                refresh_token=a.get("refresh_token", ""),
                failures=old.failures if old else 0,
                unhealthy_at=old.unhealthy_at if old else 0.0,
            ))
        self._cursor = 0

    def _usable(self, s: AccountSlot) -> bool:
        if s.unhealthy_at == 0:
            return True
        return time.time() - s.unhealthy_at >= self.cooldown_seconds

    def next(self) -> AccountSlot:
        if not self._slots:
            raise RuntimeError("无可用账号,请先补充账号")
        for _ in range(len(self._slots)):
            slot = self._slots[self._cursor % len(self._slots)]
            self._cursor += 1
            if self._usable(slot):
                return slot
        raise RuntimeError("全部账号冷却中")

    def report_failure(self, email: str) -> None:
        for s in self._slots:
            if s.email == email:
                s.failures += 1
                if s.failures >= self.fail_threshold:
                    s.unhealthy_at = time.time()
                    s.failures = 0
                    self.store.update_account_health(email, "unhealthy")
                return

    def report_success(self, email: str) -> None:
        for s in self._slots:
            if s.email == email:
                s.failures = 0
                return
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_account_pool.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add app/gateway/account_pool.py tests/test_account_pool.py
git commit -m "feat: 账号池(轮询/失败切换/健康状态)"
```

---

### Task 4: OpenAI 兼容适配层

**Files:**
- Create: `app/gateway/adapter.py`
- Test: `tests/test_adapter.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_adapter.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gateway.adapter import (
    to_openai_chunk,
    to_openai_error,
    to_trae_messages,
)


def test_to_openai_chunk():
    trae_ev = {"choices": [{"delta": {"content": "你好"}}]}
    chunk = to_openai_chunk(trae_ev, model="trae-default", idx=1)
    assert chunk["id"].startswith("chatcmpl-")
    assert chunk["model"] == "trae-default"
    assert chunk["choices"][0]["delta"]["content"] == "你好"
    assert chunk["choices"][0]["index"] == 0


def test_done_chunk():
    done = to_openai_chunk(None, model="m", idx=2)
    assert done["choices"][0]["finish_reason"] == "stop"
    assert done["choices"][0]["delta"] == {}


def test_to_openai_error():
    err = to_openai_error("quota exhausted", status=429)
    assert err["error"]["message"] == "quota exhausted"
    assert err["error"]["type"] == "rate_limit_error"


def test_to_trae_messages():
    msgs = to_trae_messages([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ])
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "hi"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_adapter.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现**

创建 `app/gateway/adapter.py`:

```python
"""OpenAI 兼容适配:请求/响应/SSE 转换。"""
import time
import uuid


def to_trae_messages(messages: list[dict]) -> list[dict]:
    """OpenAI messages → Trae messages(结构相同,原样透传)。"""
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def to_openai_chunk(trae_event: dict | None, *, model: str, idx: int) -> dict:
    """Trae SSE 事件 → OpenAI SSE chunk;trae_event=None 表示 [DONE]。"""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    if trae_event is None:
        return {
            "id": chunk_id, "object": "chat.completion.chunk",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    choices = trae_event.get("choices", [])
    first = choices[0] if choices else {}
    delta = first.get("delta", {}) or {}
    return {
        "id": chunk_id, "object": "chat.completion.chunk",
        "created": int(time.time()), "model": model,
        "choices": [{"index": first.get("index", 0), "delta": delta,
                     "finish_reason": first.get("finish_reason")}],
    }


def to_openai_error(message: str, status: int = 500) -> dict:
    err_type = {400: "invalid_request_error", 401: "authentication_error",
                429: "rate_limit_error", 503: "server_error"}.get(status, "server_error")
    return {"error": {"message": message, "type": err_type,
                      "code": None, "param": None}}


def sse_encode(data: dict) -> str:
    import json
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_adapter.py -v`
Expected: PASS(4 passed)

- [ ] **Step 5: 提交**

```bash
git add app/gateway/adapter.py tests/test_adapter.py
git commit -m "feat: OpenAI 兼容适配层(转换/SSE/错误映射)"
```

---

### Task 5: 网关 API 路由

**Files:**
- Modify: `app/api.py`

- [ ] **Step 1: 在 api.py 挂载网关路由**

在 `create_app` 中追加(在 WebSocket 路由之前):

```python
    from app.gateway.adapter import (sse_encode, to_openai_chunk,
                                     to_openai_error, to_trae_messages)
    from app.gateway.account_pool import AccountPool
    from app.gateway.trae_client import TraeClient
    from fastapi import Request, Response
    from fastapi.responses import StreamingResponse

    # 网关状态
    app.state.protocol_path = Path(__file__).resolve().parent.parent / "logs" / "chat_protocol.json"
    app.state.gateway_enabled = False
    app.state.account_pool = AccountPool(storage, fail_threshold=3,
                                         cooldown_seconds=300)

    def _load_protocol() -> dict:
        import json
        p = app.state.protocol_path
        if not p.exists():
            raise HTTPException(503, "聊天协议未侦察:先运行 app.gateway.recon")
        return json.loads(p.read_text(encoding="utf-8"))

    def _check_gateway_auth(request: Request) -> None:
        key = cfg.gateway_api_key
        if key:
            got = request.headers.get("authorization", "").removeprefix("Bearer ")
            if got != key:
                raise HTTPException(401, "网关密钥错误")

    @app.get("/v1/models")
    async def v1_models(request: Request):
        _check_gateway_auth(request)
        return {"object": "list", "data": [
            {"id": "trae-default", "object": "model", "owned_by": "trae"},
        ]}

    @app.post("/v1/chat/completions")
    async def v1_chat(request: Request):
        _check_gateway_auth(request)
        if not app.state.gateway_enabled:
            raise HTTPException(503, "网关未启用")
        body = await request.json()
        messages = to_trae_messages(body.get("messages", []))
        stream = bool(body.get("stream", False))
        model = body.get("model", "trae-default")

        protocol = _load_protocol()
        slot = app.state.account_pool.next()
        client = TraeClient(protocol, cookie=slot.cookie)

        async def event_stream():
            try:
                events = client.stream_chat(messages=messages, model=model,
                                            stream=True)
                for i, ev in enumerate(events):
                    yield sse_encode(to_openai_chunk(ev, model=model, idx=i))
                yield sse_encode(to_openai_chunk(None, model=model, idx=len(events)))
                app.state.account_pool.report_success(slot.email)
            except Exception as e:  # noqa: BLE001
                app.state.account_pool.report_failure(slot.email)
                yield sse_encode(to_openai_error(str(e), 502))

        if stream:
            return StreamingResponse(event_stream(),
                                     media_type="text/event-stream")
        events = client.stream_chat(messages=messages, model=model, stream=False)
        content = ""
        for ev in events:
            for ch in ev.get("choices", []):
                content += (ch.get("delta", {}) or {}).get("content", "")
        app.state.account_pool.report_success(slot.email)
        return {"id": "chatcmpl-x", "object": "chat.completion",
                "created": int(__import__("time").time()), "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant",
                                                     "content": content},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0}}

    @app.post("/api/gateway/enable")
    async def gateway_enable(enabled: bool = True):
        app.state.gateway_enabled = enabled
        if enabled:
            app.state.account_pool.reload()
        return {"ok": True, "enabled": app.state.gateway_enabled,
                "accounts": len(app.state.account_pool._slots)}

    @app.get("/api/gateway/status")
    async def gateway_status():
        return {"enabled": app.state.gateway_enabled,
                "accounts": len(app.state.account_pool._slots),
                "protocol_ready": app.state.protocol_path.exists()}
```

- [ ] **Step 2: 写测试**

创建 `tests/test_gateway_api.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.storage import Storage


@pytest.fixture
def client(tmp_path):
    storage = Storage(tmp_path / "t.db")
    storage.create_account(email="a@b.com", password="pw", engine="browser",
                           cookie="session=abc", health_status="healthy")
    app = create_app(storage=storage, concurrency=2)
    # 写入 mock 协议
    proto = tmp_path / "chat_protocol.json"
    proto.write_text(json.dumps({
        "chat_endpoint": "https://mock.trae/v1/chat",
        "method": "POST",
        "auth": {"type": "cookie", "cookie_name": "session"},
        "request_body": {"messages": "list", "model": "str", "stream": "bool"},
        "response_format": "sse",
    }), encoding="utf-8")
    app.state.protocol_path = proto
    with TestClient(app) as c:
        yield c


def test_models_endpoint(client):
    r = client.get("/v1/models")
    assert r.status_code == 200
    assert r.json()["data"][0]["id"] == "trae-default"


def test_chat_requires_gateway_enabled(client):
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user",
                                                                "content": "hi"}]})
    assert r.status_code == 503


def test_enable_then_status(client):
    r = client.post("/api/gateway/enable", params={"enabled": True})
    assert r.status_code == 200
    assert r.json()["accounts"] == 1
```

- [ ] **Step 3: 跑测试确认通过**

Run: `python -m pytest tests/test_gateway_api.py -v`
Expected: PASS(3 passed)

- [ ] **Step 4: 提交**

```bash
git add app/api.py tests/test_gateway_api.py
git commit -m "feat: 网关 API(/v1/models, /v1/chat/completions, 启停/状态)"
```

---

### Task 6: Web 网关面板

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`

- [ ] **Step 1: 前端加入网关面板**

在 `web/index.html` 的 `</body>` 前追加:

```html
  <div class="card">
    <h3>反代网关</h3>
    <button id="gw-enable">启用</button>
    <button id="gw-disable">停用</button>
    <pre id="gw-status"></pre>
  </div>
```

在 `web/app.js` 追加:

```javascript
async function gwStatus() {
  const r = await fetch("/api/gateway/status");
  $("gw-status").textContent = JSON.stringify(await r.json(), null, 2);
}
async function gwSet(on) {
  await fetch(`/api/gateway/enable?enabled=${on}`, { method: "POST" });
  gwStatus();
}
$("gw-enable").addEventListener("click", () => gwSet(true));
$("gw-disable").addEventListener("click", () => gwSet(false));
gwStatus();
```

- [ ] **Step 2: 提交**

```bash
git add web/
git commit -m "feat: Web 网关面板(启停/状态)"
```

---

### Task 7: 端到端冒烟

**Files:**
- 无(验证)

- [ ] **Step 1: 启动服务**

Run: `python -m uvicorn app.api:create_app --factory --port 8000`

- [ ] **Step 2: 启用网关 + 对话**

```bash
curl -s -X POST "http://localhost:8000/api/gateway/enable?enabled=true"
curl -s -X POST "http://localhost:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"trae-default","stream":true,"messages":[{"role":"user","content":"Reply OK only"}]}'
```

Expected: SSE 流式输出 `data: {...}` 至 `data: [DONE]`

- [ ] **Step 3: 失败切换验证**

把账号 cookie 改错 → 再次对话 → 应返回 502 错误事件,账号被标记 unhealthy,下一账号接管(有第二个账号时)。

- [ ] **Step 4: 提交(如有修复)**

```bash
git add -A
git commit -m "fix: 网关端到端冒烟修复"
```

---

## 阶段二验收

- [ ] `pytest` 全绿
- [ ] `/v1/models` 与 `/v1/chat/completions`(stream + 非 stream)可用
- [ ] 账号失败自动切换、健康状态持久化
- [ ] 网关密钥认证生效(配置后未带 key 返回 401)
- [ ] Web 面板可启停网关、查看账号数与协议状态
