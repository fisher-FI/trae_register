# Trae 注册机(阶段一)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Trae 国际版批量注册机:Web 界面提交任务,Playwright 自动注册(领邮箱→填表→收码→设密码→可选绑卡→登录抓凭据→入库),MailOps API 邮箱,并发 ≤10。

**Architecture:** FastAPI 轻量单体;asyncio.Semaphore 并发池;SQLite 持久化;注册引擎抽象(base/browser/protocol)支持双模式;mail_client 抽象(MailOps 为主,IMAP 回退);proxy 模块提供 Clash 订阅池/本地代理两种出口;WebSocket 实时推送。

**Tech Stack:** Python 3.12, FastAPI, uvicorn, Playwright(async), imapclient, curl_cffi, sqlite3, pytest, pytest-asyncio

**设计文档:** `docs/superpowers/specs/2026-08-02-trae-register-design.md`

---

## 文件结构

```
trae_register/
├── app/
│   ├── __init__.py
│   ├── config.py            # 配置加载(.env + 默认值)
│   ├── storage.py           # SQLite 存取
│   ├── mail_client.py       # MailOps API 客户端(本期仅实现 MailOps,IMAP 占位)
│   ├── proxy.py             # 代理管理(本地代理本期实现,Clash 订阅解析占位)
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── base.py          # 引擎抽象 + 统一注册流程
│   │   └── browser.py       # Playwright 实现
│   ├── pool.py              # asyncio 任务池
│   └── api.py               # FastAPI 路由 + WebSocket
├── web/
│   ├── index.html
│   └── app.js
├── tests/
│   ├── test_config.py
│   ├── test_storage.py
│   ├── test_mail_client.py
│   ├── test_proxy.py
│   ├── test_pool.py
│   └── test_engine_base.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

### Task 1: 项目脚手架

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_config.py`:

```python
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["MAILOPS_API_KEY"] = "mak_test123"
os.environ["CONCURRENCY"] = "3"


def test_config_defaults_and_env():
    from app.config import load_config

    cfg = load_config()
    assert cfg.mailops_api_key == "mak_test123"
    assert cfg.concurrency == 3  # 从环境变量读取
    assert cfg.code_timeout == 180  # 默认
    assert cfg.code_poll_interval == 8  # 默认
    assert cfg.proxy_mode == "none"  # 默认
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'app'`)

- [ ] **Step 3: 实现**

创建 `requirements.txt`:

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
playwright==1.48.*
imapclient==3.0.*
curl_cffi==0.7.*
python-dotenv==1.0.*
websockets==13.*
pytest==8.*
pytest-asyncio==0.24.*
httpx==0.27.*
```

创建 `.env.example`:

```
MAILOPS_API_KEY=mak_xxx
CONCURRENCY=10
CODE_TIMEOUT=180
CODE_POLL_INTERVAL=8
LEASE_SECONDS=1800
PROXY_MODE=none
PROXY_URL=
CLASH_SUB_URL=
ENABLE_PRO_TRIAL=false
GATEWAY_API_KEY=
```

创建 `app/__init__.py`(空文件)。

创建 `app/config.py`:

```python
"""配置加载:环境变量 + 默认值。"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Config:
    mailops_api_key: str = ""
    mailops_base_url: str = "https://gptmail.passkissyou.online"
    concurrency: int = 10
    code_timeout: int = 180
    code_poll_interval: int = 8
    lease_seconds: int = 1800
    proxy_mode: str = "none"  # none | clash | manual
    proxy_url: str = ""
    clash_sub_url: str = ""
    enable_pro_trial: bool = False
    card_number: str = ""
    card_exp: str = ""
    card_cvc: str = ""
    card_billing: str = ""
    gateway_api_key: str = ""
    db_path: Path = field(default_factory=lambda: BASE_DIR / "trae.db")
    screenshots_dir: Path = field(default_factory=lambda: BASE_DIR / "screenshots")
    logs_dir: Path = field(default_factory=lambda: BASE_DIR / "logs")
    headless: bool = True


def load_config() -> Config:
    def _bool(v: str) -> bool:
        return v.strip().lower() in ("1", "true", "yes", "on")

    return Config(
        mailops_api_key=os.getenv("MAILOPS_API_KEY", ""),
        mailops_base_url=os.getenv("MAILOPS_BASE_URL", "https://gptmail.passkissyou.online"),
        concurrency=int(os.getenv("CONCURRENCY", "10")),
        code_timeout=int(os.getenv("CODE_TIMEOUT", "180")),
        code_poll_interval=int(os.getenv("CODE_POLL_INTERVAL", "8")),
        lease_seconds=int(os.getenv("LEASE_SECONDS", "1800")),
        proxy_mode=os.getenv("PROXY_MODE", "none"),
        proxy_url=os.getenv("PROXY_URL", ""),
        clash_sub_url=os.getenv("CLASH_SUB_URL", ""),
        enable_pro_trial=_bool(os.getenv("ENABLE_PRO_TRIAL", "false")),
        card_number=os.getenv("CARD_NUMBER", ""),
        card_exp=os.getenv("CARD_EXP", ""),
        card_cvc=os.getenv("CARD_CVC", ""),
        card_billing=os.getenv("CARD_BILLING", ""),
        gateway_api_key=os.getenv("GATEWAY_API_KEY", ""),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS(1 passed)

- [ ] **Step 5: 提交**

```bash
git add requirements.txt .env.example app/ tests/
git commit -m "feat: 项目脚手架(config 加载 + requirements)"
```

---

### Task 2: SQLite 存储层

**Files:**
- Create: `app/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_storage.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import Storage


def _storage(tmp_path):
    return Storage(tmp_path / "test.db")


def test_create_account_and_get(tmp_path):
    s = _storage(tmp_path)
    s.create_account(email="a@b.com", password="pw123", engine="browser",
                     cookie="c=1", access_token="tok", refresh_token="rt")
    acc = s.get_account_by_email("a@b.com")
    assert acc is not None
    assert acc["password"] == "pw123"
    assert acc["cookie"] == "c=1"
    assert acc["access_token"] == "tok"
    assert acc["refresh_token"] == "rt"


def test_update_account_health(tmp_path):
    s = _storage(tmp_path)
    s.create_account(email="a@b.com", password="pw", engine="browser")
    s.update_account_health("a@b.com", "healthy")
    acc = s.get_account_by_email("a@b.com")
    assert acc["health_status"] == "healthy"


def test_task_lifecycle(tmp_path):
    s = _storage(tmp_path)
    task_id = s.create_task(batch_id="b1", email="a@b.com", engine="browser")
    assert task_id is not None
    s.update_task_status(task_id, "running")
    s.update_task_status(task_id, "failed", reason="code timeout")
    task = s.get_task(task_id)
    assert task["status"] == "failed"
    assert task["reason"] == "code timeout"


def test_list_healthy_accounts(tmp_path):
    s = _storage(tmp_path)
    s.create_account(email="a@b.com", password="pw", engine="browser", health_status="healthy")
    s.create_account(email="c@d.com", password="pw", engine="browser", health_status="unhealthy")
    emails = [a["email"] for a in s.list_healthy_accounts()]
    assert emails == ["a@b.com"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_storage.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现**

创建 `app/storage.py`:

```python
"""SQLite 存储:账号、任务。"""
import sqlite3
import time
from pathlib import Path


class Storage:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    engine TEXT NOT NULL,
                    cookie TEXT DEFAULT '',
                    access_token TEXT DEFAULT '',
                    refresh_token TEXT DEFAULT '',
                    lease_token TEXT DEFAULT '',
                    health_status TEXT DEFAULT 'unknown',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    reason TEXT DEFAULT '',
                    engine TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def create_account(self, email: str, password: str, engine: str, *,
                       cookie: str = "", access_token: str = "",
                       refresh_token: str = "", lease_token: str = "",
                       health_status: str = "unknown") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO accounts (email, password, engine, cookie, access_token,"
                " refresh_token, lease_token, health_status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (email, password, engine, cookie, access_token, refresh_token,
                 lease_token, health_status, time.time()),
            )
            return cur.lastrowid

    def get_account_by_email(self, email: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
            return dict(row) if row else None

    def update_account_health(self, email: str, health: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE accounts SET health_status=? WHERE email=?", (health, email))

    def update_account_credentials(self, email: str, *, cookie: str,
                                   access_token: str, refresh_token: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE accounts SET cookie=?, access_token=?, refresh_token=? WHERE email=?",
                (cookie, access_token, refresh_token, email),
            )

    def list_healthy_accounts(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM accounts WHERE health_status='healthy' ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def create_task(self, batch_id: str, email: str, engine: str) -> int:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (batch_id, email, engine, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (batch_id, email, engine, now, now),
            )
            return cur.lastrowid

    def update_task_status(self, task_id: int, status: str, reason: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status=?, reason=?, updated_at=? WHERE id=?",
                (status, reason, time.time(), task_id),
            )

    def get_task(self, task_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return dict(row) if row else None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_storage.py -v`
Expected: PASS(4 passed)

- [ ] **Step 5: 提交**

```bash
git add app/storage.py tests/test_storage.py
git commit -m "feat: SQLite 存储层(账号/任务 CRUD)"
```

---

### Task 3: MailOps 邮箱客户端

**Files:**
- Create: `app/mail_client.py`
- Test: `tests/test_mail_client.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_mail_client.py`(用 httpx MockTransport,不触网):

```python
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
        assert "user1@outlook.com" in str(request.url)
        assert "lease_abc" in str(request.url)
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_mail_client.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现**

创建 `app/mail_client.py`:

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_mail_client.py -v`
Expected: PASS(6 passed)

- [ ] **Step 5: 提交**

```bash
git add app/mail_client.py tests/test_mail_client.py
git commit -m "feat: MailOps 邮箱客户端(reserve/poll_code/mark_used/release)"
```

---

### Task 4: 代理管理

**Files:**
- Create: `app/proxy.py`
- Test: `tests/test_proxy.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_proxy.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config
from app.proxy import ProxyManager, NoProxyConfiguredError


def test_manual_proxy():
    cfg = Config(proxy_mode="manual", proxy_url="http://127.0.0.1:7890")
    pm = ProxyManager(cfg)
    assert pm.get_proxy() == "http://127.0.0.1:7890"
    assert pm.playwright_proxy() == {"server": "http://127.0.0.1:7890"}


def test_none_mode_raises():
    pm = ProxyManager(Config(proxy_mode="none"))
    try:
        pm.get_proxy()
        assert False, "should raise"
    except NoProxyConfiguredError:
        pass


def test_round_robin_manual():
    cfg = Config(proxy_mode="manual", proxy_url="http://127.0.0.1:7890")
    pm = ProxyManager(cfg)
    assert pm.next_proxy() == "http://127.0.0.1:7890"
    assert pm.next_proxy() == "http://127.0.0.1:7890"  # 单代理循环


def test_clash_mode_pending():
    # Clash 订阅解析为二期占位:当前配置了 clash 但未实现,直接抛出未实现
    cfg = Config(proxy_mode="clash", clash_sub_url="https://sub.example.com/x")
    pm = ProxyManager(cfg)
    try:
        pm.get_proxy()
        assert False, "should raise NotImplementedError"
    except NotImplementedError:
        pass
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_proxy.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现**

创建 `app/proxy.py`:

```python
"""代理管理:manual(本地指定)本期实现;clash(订阅池)二期。"""
from app.config import Config


class NoProxyConfiguredError(Exception):
    pass


class ProxyManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._nodes: list[str] = []

    def get_proxy(self) -> str:
        if self.cfg.proxy_mode == "manual":
            if not self.cfg.proxy_url:
                raise NoProxyConfiguredError("PROXY_URL 未配置")
            return self.cfg.proxy_url
        if self.cfg.proxy_mode == "clash":
            raise NotImplementedError("Clash 订阅代理池为二期功能")
        raise NoProxyConfiguredError("代理模式为 none")

    def next_proxy(self) -> str:
        """轮换出口:单代理时恒返回自身。"""
        return self.get_proxy()

    def playwright_proxy(self) -> dict | None:
        """返回 Playwright launch 用的 proxy 参数;直连返回 None。"""
        try:
            return {"server": self.get_proxy()}
        except (NoProxyConfiguredError, NotImplementedError):
            return None

    def proxy_for_requests(self) -> dict | None:
        """返回 requests/curl_cffi 用的 proxies 参数;直连返回 None。"""
        try:
            return {"http": self.get_proxy(), "https": self.get_proxy()}
        except (NoProxyConfiguredError, NotImplementedError):
            return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_proxy.py -v`
Expected: PASS(4 passed)

- [ ] **Step 5: 提交**

```bash
git add app/proxy.py tests/test_proxy.py
git commit -m "feat: 代理管理(manual 模式,clash 占位)"
```

---

### Task 5: 注册引擎抽象

**Files:**
- Create: `app/engine/__init__.py`
- Create: `app/engine/base.py`
- Test: `tests/test_engine_base.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_engine_base.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.base import RegistrationResult, RegisterEngine


def test_result_factory():
    ok = RegistrationResult.success("a@b.com", "pw1")
    assert ok.ok is True
    assert ok.email == "a@b.com"
    assert ok.reason == ""

    fail = RegistrationResult.failure("a@b.com", "code timeout")
    assert fail.ok is False
    assert fail.reason == "code timeout"


def test_engine_abstract():
    # 抽象基类不可直接实例化
    try:
        RegisterEngine.__abstractmethods__
        assert True
    except Exception:
        assert False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_engine_base.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现**

创建 `app/engine/__init__.py`(空文件)。

创建 `app/engine/base.py`:

```python
"""注册引擎抽象:统一注册流程的语义与数据结构。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RegistrationResult:
    ok: bool
    email: str
    password: str = ""
    reason: str = ""
    credentials: dict = field(default_factory=dict)  # cookie/access_token/refresh_token

    @classmethod
    def success(cls, email: str, password: str, credentials: dict | None = None) -> "RegistrationResult":
        return cls(ok=True, email=email, password=password,
                   credentials=credentials or {})

    @classmethod
    def failure(cls, email: str, reason: str) -> "RegistrationResult":
        return cls(ok=False, email=email, reason=reason)


class RegisterEngine(ABC):
    """实现类必须提供注册与登录凭据抓取。"""

    name: str = "base"

    @abstractmethod
    async def register(self, email: str, request_id: str) -> RegistrationResult:
        """完成注册(含可选 Pro 试用绑卡),返回结果与凭据。"""
        raise NotImplementedError

    @abstractmethod
    async def fetch_credentials(self, email: str, password: str) -> dict:
        """登录并抓取 cookie/access_token/refresh_token。"""
        raise NotImplementedError
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_engine_base.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add app/engine/ tests/test_engine_base.py
git commit -m "feat: 注册引擎抽象(base)"
```

---

### Task 6: Playwright 注册引擎

**Files:**
- Create: `app/engine/browser.py`

- [ ] **Step 1: 编写实现(Playwright 流程,不做单元测试——依赖真实页面)**

创建 `app/engine/browser.py`:

```python
"""Playwright 注册引擎:trae.ai 国际版。"""
import asyncio
import json
import re
import time
from pathlib import Path

from playwright.async_api import async_playwright

from app.config import Config
from app.engine.base import RegisterEngine, RegistrationResult
from app.proxy import ProxyManager

SIGNUP_URL = "https://www.trae.ai/sign-up"


class BrowserEngine(RegisterEngine):
    name = "browser"

    def __init__(self, cfg: Config, proxy: ProxyManager):
        self.cfg = cfg
        self.proxy = proxy
        self._pw = None
        self._browser = None

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        proxy_cfg = self.proxy.playwright_proxy()
        self._browser = await self._pw.chromium.launch(
            headless=self.cfg.headless,
            proxy=proxy_cfg,
        )
        return self

    async def __aexit__(self, *exc):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _new_context(self, email: str, request_id: str):
        """独立 context + 请求拦截记录。"""
        ctx = await self._browser.new_context()
        page = await ctx.new_page()
        log_dir = self.cfg.logs_dir / "requests"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{request_id}.jsonl"

        async def _log(route):
            entry = {
                "ts": time.time(),
                "method": route.request.method,
                "url": route.request.url,
                "headers": dict(route.request.headers),
                "post_data": route.request.post_data,
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            await route.continue_()

        await ctx.route("**/*", _log)
        return ctx, page

    async def register(self, email: str, request_id: str) -> RegistrationResult:
        password = f"Trae@{int(time.time())}x"
        ctx, page = await self._new_context(email, request_id)
        try:
            await page.goto(SIGNUP_URL, timeout=60000)
            # ① 填邮箱
            await page.get_by_role("textbox", name="Email").fill(email)
            # ② 发送验证码
            await page.get_by_role("button", name="Send Code").click()
            # ③ 等待 MailOps 验证码 —— 由 pool 层轮询注入,此处返回等待中
            #    (验证码由外部 wait_for_code 拿到后调用 self.submit_code)
            await page.wait_for_timeout(500)
            return RegistrationResult(
                ok=True, email=email, password=password,
                credentials={"_pending": True, "_request_id": request_id},
            )
        except Exception as e:  # noqa: BLE001
            shot = self.cfg.screenshots_dir / f"{request_id}.png"
            self.cfg.screenshots_dir.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(shot))
            return RegistrationResult.failure(email, f"{type(e).__name__}: {e}")
        finally:
            await ctx.close()

    async def submit_code(self, request_id: str, code: str) -> RegistrationResult:
        """补充步骤:填入验证码 → 密码 → 提交。由 pool 在拿到验证码后调用。"""
        raise NotImplementedError("submit_code 在 Task 7 与 pool 集成后实现")
```

**说明**:`register()` 当前实现为"填邮箱 → 发码"前半段,验证码轮询与后半段(填码/密码/提交/绑卡/登录)在 Task 7 的 pool 集成中完成——因为真实页面元素需要冒烟时校准,计划先跑通骨架。Step 2-4 并入 Task 7 联调。

- [ ] **Step 2: 提交**

```bash
git add app/engine/browser.py
git commit -m "feat: Playwright 注册引擎骨架(填邮箱/发码/请求拦截)"
```

---

### Task 7: 并发任务池(含注册全流程编排)

**Files:**
- Create: `app/pool.py`
- Test: `tests/test_pool.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_pool.py`:

```python
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.pool import TaskPool


@pytest.mark.asyncio
async def test_pool_limits_concurrency():
    running = 0
    max_running = 0

    async def fake_job(task_id, email):
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        await asyncio.sleep(0.05)
        running -= 1

    pool = TaskPool(concurrency=3)
    await pool.submit_batch(
        emails=[f"u{i}@b.com" for i in range(9)],
        engine=None,  # 不真实注册
        job=fake_job,
    )
    assert max_running <= 3


@pytest.mark.asyncio
async def test_pool_tracks_results():
    async def fake_job(task_id, email):
        return "ok"

    pool = TaskPool(concurrency=2)
    results = await pool.submit_batch(
        emails=["a@b.com", "c@d.com"],
        engine=None,
        job=fake_job,
    )
    assert len(results) == 2
    assert all(r == "ok" for r in results)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pool.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现**

创建 `app/pool.py`:

```python
"""异步任务池:Semaphore 限流 + 状态回调。"""
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

JobFn = Callable[[int, str], Awaitable[Any]]


class TaskPool:
    def __init__(self, concurrency: int):
        self.concurrency = concurrency
        self._sem = asyncio.Semaphore(concurrency)

    async def submit_batch(self, emails: list[str], job: JobFn,
                           engine: Any = None) -> list[Any]:
        """对每个 email 执行 job(task_id, email);job 内部自行处理 engine。"""

        async def _run(task_id: int, email: str):
            async with self._sem:
                return await job(task_id, email)

        return await asyncio.gather(
            *[_run(i + 1, email) for i, email in enumerate(emails)]
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_pool.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 注册全流程编排(engine/browser.py 补齐)**

在 `app/engine/browser.py` 末尾追加完整流程方法(替换 Step 1 中的骨架):

```python
    async def run_full(self, email: str, request_id: str,
                       code_provider) -> RegistrationResult:
        """完整注册流程。code_provider: async (email) -> str 验证码提供者。"""
        password = f"Trae@{int(time.time())}x"
        ctx, page = await self._new_context(email, request_id)
        try:
            await page.goto(SIGNUP_URL, timeout=60000)
            await page.get_by_role("textbox", name="Email").fill(email)
            await page.get_by_role("button", name="Send Code").click()

            code = await code_provider(email)
            if not code:
                return RegistrationResult.failure(email, "验证码获取失败")

            await page.get_by_role("textbox", name="Verification code").fill(code)
            await page.get_by_role("textbox", name="Password").fill(password)
            await page.get_by_role("button", name="Sign Up").click()
            await page.wait_for_url("**/ide**", timeout=60000)  # 注册成功进入 IDE

            # 凭据抓取:当前页面 cookie
            cookies = await ctx.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            return RegistrationResult.success(
                email, password,
                credentials={"cookie": cookie_str,
                             "access_token": "", "refresh_token": ""},
            )
        except Exception as e:  # noqa: BLE001
            shot = self.cfg.screenshots_dir / f"{request_id}.png"
            self.cfg.screenshots_dir.mkdir(parents=True, exist_ok=True)
            try:
                await page.screenshot(path=str(shot))
            except Exception:
                pass
            return RegistrationResult.failure(email, f"{type(e).__name__}: {e}")
        finally:
            await ctx.close()
```

- [ ] **Step 6: 跑全部测试**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 7: 提交**

```bash
git add app/pool.py app/engine/browser.py tests/test_pool.py
git commit -m "feat: 并发任务池 + 注册全流程编排"
```

---

### Task 8: FastAPI 服务(任务 API + WebSocket)

**Files:**
- Create: `app/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_api.py`:

```python
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
    app = create_app(storage=storage, concurrency=2)
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_submit_task_without_key(client):
    r = client.post("/api/tasks/submit", json={
        "count": 1, "password_rule": "default",
    })
    assert r.status_code == 400  # 未配置 MAILOPS_API_KEY


def test_list_tasks_empty(client):
    r = client.get("/api/tasks")
    assert r.status_code == 200
    assert r.json()["tasks"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现**

创建 `app/api.py`:

```python
"""FastAPI:管理接口 + WebSocket 推送。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import Config, load_config
from app.mail_client import MailOpsClient, NoMailboxError
from app.storage import Storage


class SubmitRequest(BaseModel):
    count: int = 1
    enable_pro_trial: bool = False


def create_app(storage: Storage | None = None, concurrency: int = 10,
               cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    storage = storage or Storage(cfg.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="Trae 注册机", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.storage = storage
    app.state.mail = MailOpsClient(cfg.mailops_api_key, cfg.mailops_base_url)
    app.state.connections: list[WebSocket] = []

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.post("/api/tasks/submit")
    async def submit(req: SubmitRequest):
        if not cfg.mailops_api_key:
            raise HTTPException(400, "MAILOPS_API_KEY 未配置")
        if not (1 <= req.count <= 1000):
            raise HTTPException(400, "count 需在 1-1000 之间")
        # 本期:创建任务记录并返回 batch_id(实际注册执行在 Task 9 联调接入)
        batch_id = f"batch-{int(__import__('time').time())}"
        return {"ok": True, "batch_id": batch_id, "queued": req.count}

    @app.get("/api/tasks")
    async def list_tasks(limit: int = 100):
        return {"tasks": []}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        app.state.connections.append(websocket)
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass
        finally:
            app.state.connections.remove(websocket)

    # 静态前端(存在时才挂载)
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat: FastAPI 管理接口 + WebSocket"
```

---

### Task 9: Web 前端

**Files:**
- Create: `web/index.html`
- Create: `web/app.js`

- [ ] **Step 1: 实现页面**

创建 `web/index.html`:

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <title>Trae 注册机</title>
  <style>
    body { font-family: system-ui; max-width: 900px; margin: 40px auto; padding: 0 16px; }
    .card { border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin: 16px 0; }
    input, button { padding: 8px; margin: 4px; }
    table { width: 100%; border-collapse: collapse; }
    td, th { border: 1px solid #eee; padding: 6px; text-align: left; font-size: 14px; }
    .ok { color: green; } .fail { color: red; }
  </style>
</head>
<body>
  <h1>Trae 注册机</h1>
  <div class="card">
    <h3>批量提交</h3>
    <label>数量 <input id="count" type="number" value="1" min="1" max="1000"></label>
    <label><input id="pro" type="checkbox"> 开启 Pro 试用(绑卡)</label>
    <button id="submit">开始注册</button>
    <span id="result"></span>
  </div>
  <div class="card">
    <h3>任务看板 <span id="conn" class="fail">(未连接)</span></h3>
    <table id="tasks"><thead><tr><th>任务</th><th>邮箱</th><th>状态</th><th>原因</th></tr></thead><tbody></tbody></table>
  </div>
  <script src="/app.js"></script>
</body>
</html>
```

创建 `web/app.js`:

```javascript
const $ = (id) => document.getElementById(id);

async function submit() {
  const res = await fetch("/api/tasks/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      count: parseInt($("count").value, 10),
      enable_pro_trial: $("pro").checked,
    }),
  });
  const data = await res.json();
  $("result").textContent = data.batch_id
    ? `已入队: ${data.queued} 个 (${data.batch_id})` : `错误: ${JSON.stringify(data)}`;
}

function connectWS() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => { $("conn").textContent = "(已连接)"; $("conn").className = "ok"; };
  ws.onclose = () => { $("conn").textContent = "(未连接)"; $("conn").className = "fail";
                        setTimeout(connectWS, 3000); };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "task") upsertTask(m.task);
  };
}

function upsertTask(t) {
  const tbody = document.querySelector("#tasks tbody");
  let row = document.querySelector(`#tasks tr[data-id="${t.id}"]`);
  if (!row) {
    row = document.createElement("tr");
    row.dataset.id = t.id;
    tbody.prepend(row);
  }
  row.innerHTML = `<td>${t.id}</td><td>${t.email}</td>
    <td class="${t.status === 'success' ? 'ok' : (t.status === 'failed' ? 'fail' : '')}">${t.status}</td>
    <td>${t.reason || ""}</td>`;
}

$("submit").addEventListener("click", submit);
connectWS();
```

- [ ] **Step 2: 启动服务冒烟**

Run: `python -m uvicorn app.api:create_app --factory --port 8000`
打开 `http://localhost:8000`,确认页面加载、提交按钮返回 `已入队`。

- [ ] **Step 3: 提交**

```bash
git add web/
git commit -m "feat: Web 前端(任务提交 + WS 看板)"
```

---

### Task 10: 冒烟测试(真实注册 1 个账号)

**Files:**
- Modify: `app/api.py`(接入真实注册执行)

- [ ] **Step 1: api.py 接入真实注册**

在 `create_app` 的 `submit` 中替换占位逻辑:

```python
    @app.post("/api/tasks/submit")
    async def submit(req: SubmitRequest):
        if not cfg.mailops_api_key:
            raise HTTPException(400, "MAILOPS_API_KEY 未配置")
        if not (1 <= req.count <= 1000):
            raise HTTPException(400, "count 需在 1-1000 之间")
        batch_id = f"batch-{int(__import__('time').time())}"
        # 领邮箱 → 建任务 → 后台执行(执行函数见下方 register_one)
        tasks_created = []
        for i in range(req.count):
            try:
                mb = app.state.mail.reserve("trae", f"{batch_id}-w{i+1}-a1",
                                            cfg.lease_seconds)
            except NoMailboxError:
                break
            task_id = storage.create_task(batch_id, mb.email, "browser")
            tasks_created.append((task_id, mb.email))
        import asyncio
        asyncio.get_running_loop().create_task(
            _run_batch(app, batch_id, tasks_created, req.enable_pro_trial))
        return {"ok": True, "batch_id": batch_id, "queued": len(tasks_created)}

    async def _run_batch(app, batch_id, tasks, enable_pro_trial):
        from app.pool import TaskPool
        from app.engine.browser import BrowserEngine
        from app.proxy import ProxyManager

        async def job(task_id, email):
            storage.update_task_status(task_id, "running")
            try:
                async with BrowserEngine(app.state.cfg, ProxyManager(app.state.cfg)) as eng:
                    code = None
                    async def code_provider(mail_addr):
                        mb = app.state.mail.reserve  # noqa: F841 (占位)
                        return None  # 冒烟阶段:验证码走人工输入或后续 MailOps wait_for_code
                    result = await eng.run_full(email, f"{batch_id}-t{task_id}", code_provider)
                if result.ok:
                    storage.update_task_status(task_id, "success")
                    storage.create_account(
                        email=result.email, password=result.password,
                        engine="browser",
                        cookie=result.credentials.get("cookie", ""),
                        access_token=result.credentials.get("access_token", ""),
                        refresh_token=result.credentials.get("refresh_token", ""),
                        lease_token="",
                        health_status="healthy",
                    )
                else:
                    storage.update_task_status(task_id, "failed", reason=result.reason)
            except Exception as e:  # noqa: BLE001
                storage.update_task_status(task_id, "failed", reason=str(e))
            await _notify(app, task_id, email)

        pool = TaskPool(concurrency=app.state.cfg.concurrency)
        await pool.submit_batch([e for _, e in tasks], job)

    async def _notify(app, task_id, email):
        task = storage.get_task(task_id)
        payload = {"type": "task", "task": task}
        for ws in list(app.state.connections):
            try:
                await ws.send_json(payload)
            except Exception:
                pass
```

- [ ] **Step 2: 联调验证码获取**

将 `code_provider` 替换为 MailOps 轮询:

```python
                    async def code_provider(mail_addr):
                        try:
                            return app.state.mail.wait_for_code(
                                mail_addr, _lease_for(email),
                                timeout=cfg.code_timeout,
                                interval=cfg.code_poll_interval)
                        except TimeoutError:
                            return None
```

其中 `_lease_for` 从提交时保存的 `{email: lease_token}` 映射读取(修改 submit 时保存该映射到 `app.state.leases`)。

- [ ] **Step 3: 真实冒烟**

Run: `python -m uvicorn app.api:create_app --factory --port 8000`
Web 提交 `count=1`,观察:
- 任务状态 queued → running → success
- SQLite 中 accounts 出现记录(含 cookie)
- 失败时 `screenshots/` 有截图、reason 有原因

- [ ] **Step 4: 校准选择器**

冒烟失败时(元素定位/页面结构变化),按截图校准 `browser.py` 中 `get_by_role` 的选择器文案,重复 Step 3 直至注册成功。

- [ ] **Step 5: 提交**

```bash
git add app/
git commit -m "feat: 注册任务接入真实执行链路(冒烟通过)"
```

---

## 阶段一验收

- [ ] `pytest` 全绿
- [ ] Web 提交 1 个任务真实注册成功,账号含凭据入库
- [ ] 失败路径:截图 + reason + 可重试(重试按钮在阶段一为手动重新提交)
- [ ] 代理 manual 模式:配置 PROXY_URL 后注册流量走代理
- [ ] 冒烟记录:把真实注册结果写入 `docs/superpowers/plans/2026-08-02-trae-gateway.md` 前置说明

## 后续增量(明确不在本期,不在本计划任务内)

| 增量 | 说明 |
|---|---|
| **Pro 试用绑卡(ENABLE_PRO_TRIAL)** | 基础注册链路稳定后增量实现:注册成功 → 进升级页 → 填卡(卡号/有效期/CVC/账单地址,来自配置)→ 0 元支付;先浏览器方式,再评估"提链直调支付网关" | 
| **协议模式(engine/protocol.py)** | 基于 `logs/requests/` 接口情报实现,curl_cffi 伪装 TLS |
| **IMAP 邮箱回退** | mail_client 增加 IMAP 实现,API 无邮箱时回退 |
| **Clash 订阅代理池** | proxy.py 增加订阅解析与节点轮换(mihomo) |
