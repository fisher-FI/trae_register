# Trae 注册机(Web 版)设计文档

日期:2026-08-02
状态:已确认

## 1. 背景与目标

开发一个 Trae(国际版 trae.ai)账号注册机,通过 Web 界面批量注册账号。邮箱来源以 MailOps API(gptmail.passkissyou.online)为主,自有邮箱 + IMAP 为回退。

**成功标准**:
- 通过 Web 界面提交批量注册任务,并发 ≤10
- 每个账号自动完成:领邮箱 → 填表注册 → 收验证码 → 设密码 → 完成入库
- 浏览器(Playwright)与协议(requests)双引擎共存,可切换
- 账号、任务、邮箱状态持久化,支持失败重试

## 2. 总体架构(轻量单体)

```
浏览器 (Web界面) ──REST/WebSocket──> FastAPI ──调度──> asyncio 任务池(并发≤10)
                                          │
                                          ├── 注册引擎(双模式可切换)
                                          │     ├── browser: Playwright 自动化
                                          │     └── protocol: requests 直连(二期)
                                          ├── mail_client: MailOps API 为主,IMAP 回退
                                          └── SQLite (账号/任务/邮箱池/配置持久化)
```

单进程、单机部署,`uvicorn` 启动,浏览器访问 `http://localhost:8000`。

## 3. 模块划分

| 模块 | 职责 |
|---|---|
| `app/config.py` | 配置加载:API key、并发数、验证码超时、轮询间隔、浏览器参数(从 `.env` + `config.toml`) |
| `app/mail_client.py` | 邮箱抽象:MailOps API 客户端为主实现,IMAP 客户端为回退实现,统一接口 `reserve() / poll_code() / mark_used() / release()` |
| `app/engine/` | 注册引擎双实现:`base.py`(统一抽象 + 任务上下文)、`browser.py`(Playwright)、`protocol.py`(requests,二期) |
| `app/pool.py` | asyncio 任务池:`Semaphore(10)` 限流,任务状态机(排队/运行中/成功/失败/重试中) |
| `app/storage.py` | SQLite:账号表、任务表、邮箱使用表 |
| `app/api.py` | FastAPI 路由 + WebSocket 实时推送 |
| `web/` | 原生 HTML/JS 单页:任务提交、进度看板、邮箱池状态、引擎切换 |

## 4. 注册流程(引擎核心)

### 4.1 统一流程(两种引擎实现同一语义)

```
① mail.reserve(platform=trae) → email + lease_token
② 打开 trae.ai/signup → 填 email 提交
③ mail.poll_code(email, lease_token) 轮询验证码(8s 间隔,默认 180s 超时)
④ 填入验证码 → 设置密码 → 提交
⑤ 成功 → mail.mark_used(上报账号资料) → 账号入库
   失败 → mail.release(归还邮箱) → 任务失败,原因记录
```

### 4.2 浏览器模式(browser.py)

- Playwright async API,每任务独立 `browser context`(独立 cookie/指纹)
- 全程 `page.route` 拦截记录网络请求到 `logs/requests/`(为协议模式积累接口情报)
- 失败自动截图到 `screenshots/`

### 4.3 协议模式(protocol.py,二期)

- 基于浏览器模式拦截到的接口情报实现
- `curl_cffi` 伪装 TLS 指纹;签名参数需逆向时标记 TODO 由浏览器混合兜底
- 复用同一 `mail_client` 与任务状态机,不触碰其他模块

## 5. MailOps API 集成(已实测)

**实测结论(2026-08-02,使用用户 API key)**:
- `GET /api/reuse/v1/platforms` 返回 ok,`trae` 平台可用(reserve 时服务端动态注册)
- `POST /api/reuse/v1/mail/reserve` body `{"platform":"trae","request_id":"...","lease_seconds":1800}` → 返回 `email` + `lease_token`;邮箱为空时 `reason=no_available`
- `GET /api/mail/code?email=&lease_token=&keyword=code,验证码,verification code,trae&limit=10&folders=inbox,junk` → `found=true` 时有码
- `POST /api/reuse/v1/mail/mark-used`(成功/可能占用)与 `POST /api/reuse/v1/mail/release`(确认未占用)
- 返回邮箱为 Outlook 资产(含 password/refresh_token),`max_mailbox_uses=3`
- `request_id` 格式建议:`batch-{batch_id}-worker-{n}-attempt-{m}`

**关键约束**:收码、mark-used、release 都必须携带正确 `lease_token`,错误返回 409;不要用 summary/mailboxes 接口分配邮箱(仅诊断)。

## 6. 任务与并发

- 提交批量任务 → 拆分为子任务入队
- `asyncio.Semaphore(10)` 限流(参考开源项目建议,并发过高失败率上升)
- 任务状态机:queued → running → success / failed(reason)/ retry
- 失败可一键重试:retry 时优先复用原 lease(未过期),否则重新 reserve
- WebSocket 推送每任务状态变更

## 7. 存储设计(SQLite)

```sql
accounts(id, email, password, status, engine, lease_token, created_at)
tasks(id, batch_id, email, status, reason, engine, created_at, updated_at)
mailboxes(id, email, platform, lease_token, status, reserved_at, used_at)  -- 使用记录
```

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| 验证码超时(180s) | 任务失败,release 邮箱,记录原因,可重试 |
| API 无可用邮箱(no_available) | 回退 IMAP 邮箱池;仍无则任务排队等待 |
| IMAP 连接失败 | 重试 3 次,退避 2s |
| 页面元素找不到 | 截图 + 失败原因入库 |
| mark-used/release 409 | lease 失效,标记任务需人工复核 |
| 并发控制 | Semaphore 保证 ≤10 |

## 9. Web 界面(web/)

单页(index.html + app.js):
- 引擎选择(浏览器/协议,协议二期再启用)
- 批量提交:数量、并发数、密码规则
- 任务看板:状态、进度、失败原因、重试按钮
- 邮箱池状态面板(来自 summary 接口,只读诊断)
- WebSocket 实时刷新

## 10. 合规

- README 含免责声明:仅供学习研究,遵守 Trae 服务条款,禁止商业用途(与开源同类项目一致)
- `.env`(API key)已加入 `.gitignore`,不提交

## 11. 项目结构

```
trae_register/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── mail_client.py      # MailOps API 为主 + IMAP 回退
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── base.py         # 注册引擎抽象 + 统一流程
│   │   ├── browser.py      # Playwright 实现
│   │   └── protocol.py     # requests 实现(二期)
│   ├── pool.py             # 并发任务池
│   ├── storage.py          # SQLite
│   └── api.py              # FastAPI + WebSocket
├── web/
│   ├── index.html
│   └── app.js
├── tests/
│   ├── test_mail_client.py
│   ├── test_pool.py
│   └── test_storage.py
├── screenshots/            # 失败截图(运行时生成)
├── logs/                   # 请求日志(运行时生成)
├── .env                    # API key(已 gitignore)
├── .gitignore
├── requirements.txt
└── README.md
```

## 12. 技术选型

- Python 3.12
- FastAPI + uvicorn + WebSocket
- Playwright(async)+ imapclient + curl_cffi(协议模式用)
- SQLite(内置 sqlite3)
- 前端原生 HTML/JS(无构建步骤)

## 13. 测试策略

- 单元测试:mail_client(Mock API 响应)、pool(状态机)、storage(CRUD)
- 集成测试:注册流程 mock 化(不真实注册)
- 手工冒烟:真实注册 1 个账号验证全链路

## 14. 二期展望(协议模式)

- 用浏览器模式积累的请求日志逆向接口
- 处理风控签名/指纹(可能需要 JS 逆向或混合模式)
- 协议模式通过同一引擎抽象无缝接入,Web 界面切换
