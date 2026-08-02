# Trae 注册机 + OpenAI 兼容反代网关 设计文档

日期:2026-08-02
状态:修订版(用户审阅中)

## 1. 背景与目标

构建一套 Trae(国际版 trae.ai)批量账号体系:

1. **注册机**:通过 Web 界面批量注册 Trae 账号,自动完成领邮箱 → 填表注册 → 收验证码 → 设密码 → **自动登录抓取凭据(cookie/token)** → 账号入库
2. **反代网关**:把 Trae 的聊天能力包装成 **OpenAI 兼容 API**(`/v1/chat/completions` 风格),账号池轮询调度,负载均衡,供任意 OpenAI SDK/客户端调用

**账号价值依据(Trae 官方定价,2026-08-02 核实)**:Trae 提供 0 元免费使用——
- **Free 档**:每个账号有有限免费使用额度(Limited usage)+ Autocomplete 5000 次/月
- **Pro 档**:新用户 7 天免费试用($0,含 $20 Basic usage + Bonus usage,之后 $10/月;**需绑定支付卡,扣费 0 元**,绑卡环节由注册机全自动完成)
- 批量注册即批量获得免费额度池;Pro 试用可作为**可选增强**(默认关闭,合规风险较高)

**注册字段(2026-08-02 调研确认)**:国际版注册全程仅 **邮箱 + 验证码 + 密码** 三字段,无手机号、无用户名(另有 GitHub/Google 快捷登录);国内版(trae.com.cn)才需要 +86 手机号,属另一套体系,不在本期范围。国际版现实瓶颈为**邮箱域名风控**——本项目用 MailOps Outlook 邮箱池规避,方案优势。

**成功标准**:
- Web 界面提交批量注册任务,并发 ≤10,账号自动入库含登录凭据
- 注册机支持浏览器(Playwright)与协议(requests)双引擎,可切换
- 反代网关提供 OpenAI 兼容 `/v1/chat/completions` + `/v1/models`,账号池轮询、失败切换、额度健康检查
- 浏览器模式全程拦截网络请求,为协议引擎与反代网关积累接口情报
- 账号、任务、凭据持久化,支持失败重试

## 2. 总体架构(轻量单体)

```
┌─────────────────────────────── 一期:注册机 ───────────────────────────────┐
│ 浏览器(Web界面)──REST/WebSocket──> FastAPI ──调度──> asyncio 任务池(≤10)  │
│                                          │                                │
│                                          ├── 注册引擎(双模式)              │
│                                          │     ├── browser: Playwright     │
│                                          │     └── protocol: requests(二期)│
│                                          ├── mail_client: MailOps API为主  │
│                                          └── SQLite(账号/凭据/任务)        │
└────────────────────────────────────────────────────────────────────────────┘
                              │ 账号凭据库(衔接点)
┌─────────────────────────────── 一期:反代网关 ─────────────────────────────┐
│ OpenAI 兼容 /v1/chat/completions ──> adapter ──> trae_client(真实聊天接口) │
│                                           ▲                                │
│                                     account_pool(凭据轮询/健康检查)        │
└────────────────────────────────────────────────────────────────────────────┘
```

单进程、单机部署,`uvicorn` 启动,浏览器访问 `http://localhost:8000`。
注册机与网关同进程,注册任务与网关请求共享账号库。

## 3. 模块划分

| 模块 | 职责 |
|---|---|
| `app/config.py` | 配置加载:API key、并发数、验证码超时、轮询间隔、浏览器参数、网关端口/密钥、代理配置 |
| `app/proxy.py` | 代理管理双模式:Clash 订阅代理池(轮换出口) / 本地指定代理出口;为注册任务与网关请求提供代理 |
| `app/mail_client.py` | 邮箱抽象:MailOps API 为主,IMAP 回退;统一 `reserve() / poll_code() / mark_used() / release()` |
| `app/engine/` | 注册引擎:`base.py`(统一抽象+流程)、`browser.py`(Playwright)、`protocol.py`(requests,二期) |
| `app/pool.py` | 注册任务池:`Semaphore(10)` 限流,状态机(排队/运行中/成功/失败/重试中) |
| `app/storage.py` | SQLite:账号表(含凭据)、任务表、邮箱使用表、网关调用日志 |
| `app/api.py` | FastAPI 路由:注册机管理接口 + 网关 OpenAI 兼容接口 + WebSocket |
| `app/gateway/` | 反代网关:`trae_client.py`(真实聊天接口)、`adapter.py`(OpenAI 兼容转换)、`account_pool.py`(凭据轮询/健康检查/限流) |
| `web/` | 原生 HTML/JS 单页:任务提交、进度看板、账号凭据导出、网关状态面板 |

## 4. 注册流程(引擎核心)

### 4.1 统一流程

```
① 分配代理出口(按代理策略,见 §7)
② mail.reserve(platform=trae) → email + lease_token
③ 打开 trae.ai/signup(经代理) → 填 email 提交
④ mail.poll_code(email, lease_token) 轮询验证码(8s 间隔,默认 180s 超时)
⑤ 填入验证码 → 设置密码 → 提交
⑥ 领取 Pro 试用(可选):进入升级页 → 绑卡支付(双实现,见下)→ 提交 0 元支付
⑦ 自动登录 → 抓取会话凭据(cookie / access_token / refresh_token)
⑧ 成功 → mail.mark_used(上报账号资料) → 账号+凭据入库
   失败 → mail.release(归还邮箱) → 任务失败,原因记录
```

### 4.2 浏览器模式(browser.py)

- Playwright async API,每任务独立 `browser context`
- 全程 `page.route` 拦截记录网络请求到 `logs/requests/`(注册接口 + 登录接口 + **聊天接口**情报)
- 失败自动截图到 `screenshots/`

### 4.3 协议模式(protocol.py,二期)

- 基于浏览器模式积累的接口情报实现
- `curl_cffi` 伪装 TLS;签名参数逆向不了的环节由浏览器混合兜底
- 复用同一 `mail_client` 与任务状态机

## 5. MailOps API 集成(已实测)

**实测结论(2026-08-02,使用用户 API key)**:
- `GET /api/reuse/v1/platforms` 返回 ok,`trae` 平台可用
- `POST /api/reuse/v1/mail/reserve` body `{"platform":"trae","request_id":"...","lease_seconds":1800}` → `email` + `lease_token`;无邮箱时 `reason=no_available`
- `GET /api/mail/code?email=&lease_token=&keyword=code,验证码,verification code,trae&limit=10&folders=inbox,junk` → `found=true` 时有码
- `POST /api/reuse/v1/mail/mark-used` / `POST /api/reuse/v1/mail/release`
- 邮箱为 Outlook 资产,`max_mailbox_uses=3`;`request_id` 格式 `batch-{batch_id}-worker-{n}-attempt-{m}`

**关键约束**:收码/mark-used/release 必须携带 `lease_token`(错误返回 409);summary/mailboxes 仅诊断,不用于分配。

## 6. 接口侦察(反代网关前置任务)

Trae 聊天接口协议未知,是反代网关的**前置依赖**。侦察方案:

1. 浏览器模式注册跑通后,用 Playwright 打开 trae.ai 登录会话
2. 在聊天页发一条消息,`page.route` 拦截并记录:
   - 聊天端点 URL(chat/completions 或自有协议)
   - 请求 headers(认证方式:Authorization Bearer? cookie?)
   - 请求 body 结构(模型名、消息格式、stream 参数)
   - 响应格式(SSE? JSON?)
3. 情报落盘 `logs/requests/chat_protocol.json`,供 `trae_client.py` 实现

**风险**:Trae 可能改端点/加密 body/校验指纹。缓解:trae_client 层做统一封装,协议变化只改该文件;必要时走浏览器混合模式(Playwright 发消息+读 SSE)。

## 7. 代理策略(proxy.py)

注册任务与网关请求的出口代理,两种模式:

| 模式 | 配置 | 说明 |
|---|---|---|
| A. Clash 订阅代理池 | `CLASH_SUB_URL`(订阅链接)+ mihomo 核心 | 解析订阅获取节点列表,每任务/会话分配独立节点(轮换出口 IP),降低批量注册风控关联;节点失败自动切换 |
| B. 本地指定代理 | `PROXY_URL`(如 `http://127.0.0.1:7890` 或 socks5) | 手动指定单个代理出口,适合已有代理客户端/机场工具的场景 |

- 模式切换:`PROXY_MODE=none|clash|manual`,默认 `none`(直连)
- 分配策略:注册任务每任务独立出口(轮换);网关请求按账号绑定出口,失败切换
- Clash 订阅:解析节点列表 → 可用性探测(轻量 HTTP 请求)→ 入池;通过 mihomo API 或内置库管理
- 启动自检:代理对 trae.ai 的连通性
- 注意:MailOps API 请求走本地直连(无需代理),仅 Trae 流量走代理

## 8. 反代网关(gateway/)

### 8.1 OpenAI 兼容层(adapter.py)

```
POST /v1/chat/completions  (可选 Authorization: Bearer <网关密钥>)
  body: {model, messages, stream, temperature, max_tokens...}
  ↓ 转换为 trae_client 请求
  ↓ 响应转换为 OpenAI 格式(含 usage、SSE chunk 格式)
GET /v1/models → 返回 trae 可用模型列表
```

- stream=true 时按 OpenAI SSE 规范(`data: {...}` / `data: [DONE]`)转发
- 超时、错误映射为 OpenAI 错误格式(`{"error": {"message": ...}}`)

### 8.2 Trae 客户端(trae_client.py)

- 基于侦察的聊天协议实现
- 会话管理:每账号保持 cookie/token 有效态,过期自动重登
- 独立封装:协议变化只改本文件

### 8.3 账号池(account_pool.py)

- 从账号库加载可用凭据
- 轮询策略:round-robin;失败切换(连续 N 次失败标记不健康,冷却后重测)
- 并发保护:每账号同时 1 个会话,全局队列限流
- 额度健康检查:定期(或按调用失败率)用轻量请求验证账号可用性;识别 Free 档额度耗尽(返回配额类错误)并标记,额度重置周期后自动恢复
- 账号耗尽 → 503 + 提示补充账号
- **Pro 试用增强(可选,默认关闭)**:`ENABLE_PRO_TRIAL` 配置开启后,注册完成自动领取 7 天 Pro 试用:
  - **需要绑卡**:升级流程要求绑定支付卡(扣费 0 元),卡信息来自配置(`CARD_NUMBER / CARD_EXP / CARD_CVC / CARD_BILLING`,见 §10 存储/§12 Web 界面)
  - **绑卡支付双实现**:
    - 方式 A(浏览器):Playwright 进升级页自动填卡提交——先跑通流程
    - 方式 B(提链直调):浏览器拦截支付环节请求,提取支付网关链接与参数(如 Stripe 的 PaymentIntent/client_secret、Paddle 等托管收银台);若网关协议可直调,则用 curl_cffi 直接 POST 卡信息完成 0 元支付,不依赖页面 DOM;直调不通时降级回方式 A
  - 支付协议情报与聊天接口情报一样落盘 `logs/requests/`(见 §6 接口侦察)
  - 风险:卡 BIN 风控、3DS 验证、账单地址校验可能导致绑卡失败 → 任务标记 needs_card_review,人工兜底(前端弹窗手动填卡)
  - 涉及滥用风险,需用户显式开启

### 8.4 网关安全(基础)

- 网关密钥(可选):`GATEWAY_API_KEY` 配置,未配置时仅监听 127.0.0.1
- 请求日志入库(gateway_logs 表),便于排查

## 9. 任务与并发(注册机)

- 提交批量任务 → 拆分子任务入队
- `asyncio.Semaphore(10)` 限流
- 状态机:queued → running → success / failed(reason) / retry
- 失败一键重试:优先复用未过期 lease,否则重新 reserve
- WebSocket 推送状态变更

## 10. 存储设计(SQLite)

```sql
accounts(id, email, password, status, engine,
         cookie, access_token, refresh_token,   -- 登录凭据(网关用)
         lease_token, last_health_check, health_status, created_at)
tasks(id, batch_id, email, status, reason, engine, created_at, updated_at)
mailboxes(id, email, platform, lease_token, status, reserved_at, used_at)
gateway_logs(id, account_id, model, stream, status, latency_ms, created_at)
```

凭据字段仅存本地 SQLite,Web 界面导出时需确认。

## 11. 错误处理

| 场景 | 处理 |
|---|---|
| 验证码超时(180s) | 任务失败,release 邮箱,记录原因,可重试 |
| API 无可用邮箱(no_available) | 回退 IMAP;仍无则排队等待 |
| IMAP 连接失败 | 重试 3 次,退避 2s |
| 页面元素找不到 | 截图 + 失败原因入库 |
| mark-used/release 409 | lease 失效,标记人工复核 |
| 登录失败/凭据抓取失败 | 账号标记 degraded,重试登录 |
| 绑卡失败(卡被拒/3DS/风控) | 任务标记 needs_card_review,前端弹窗人工填卡兜底 |
| 网关账号失败 | 切换下一账号;连续失败标记不健康+冷却 |
| 代理节点失效 | 切换池内下一节点;池耗尽降级直连并告警 |
| 网关无可用账号 | 503,提示补充账号 |

## 12. Web 界面(web/)

单页(index.html + app.js):
- 引擎选择(浏览器/协议,协议二期启用)
- 批量提交:数量、并发数、密码规则、是否开启 Pro 试用
- 卡片配置:卡号/有效期/CVC/账单地址(启用 Pro 试用时必填;3DS 等需人工的场景弹窗兜底)
- 任务看板:状态、进度、失败原因、重试按钮
- 账号库:凭据状态、健康度、导出(CSV/JSON,含凭据需二次确认)
- 网关面板:模型列表、今日调用量、账号池健康、启停开关
- 代理配置:模式切换、Clash 订阅链接、节点列表与连通状态
- WebSocket 实时刷新

## 13. 合规

- README 免责声明:仅供学习研究,遵守 Trae 服务条款,禁止商业用途
- `.env`(API key、网关密钥)已加入 `.gitignore`,不提交
- 网关默认仅本机监听,防误用

## 14. 项目结构

```
trae_register/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── mail_client.py          # MailOps API 为主 + IMAP 回退
│   ├── proxy.py                 # 代理管理(Clash 订阅池 / 本地代理)
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── base.py             # 注册引擎抽象 + 统一流程
│   │   ├── browser.py          # Playwright 实现
│   │   └── protocol.py         # requests 实现(二期)
│   ├── pool.py                 # 注册任务池
│   ├── storage.py              # SQLite
│   ├── api.py                  # FastAPI:管理接口 + 网关接口 + WebSocket
│   └── gateway/
│       ├── __init__.py
│       ├── trae_client.py      # Trae 聊天接口客户端
│       ├── adapter.py          # OpenAI 兼容转换
│       └── account_pool.py     # 账号轮询/健康检查
├── web/
│   ├── index.html
│   └── app.js
├── tests/
│   ├── test_mail_client.py
│   ├── test_pool.py
│   ├── test_storage.py
│   ├── test_adapter.py
│   └── test_account_pool.py
├── screenshots/
├── logs/                       # 请求情报 + 运行日志
├── .env                        # API key、网关密钥、卡片配置(已 gitignore)
├── .gitignore
├── requirements.txt
└── README.md
```

## 15. 技术选型

- Python 3.12
- FastAPI + uvicorn + WebSocket
- Playwright(async)+ imapclient + curl_cffi(协议模式用)
- mihomo(Clash 内核,代理模式 A 用)
- SQLite(内置 sqlite3)
- 前端原生 HTML/JS

## 16. 测试策略

- 单元:mail_client(Mock API)、pool(状态机)、storage(CRUD)、adapter(OpenAI 格式转换)、account_pool(轮询/切换)
- 集成:注册流程 mock 化;网关用 mock trae_client 验证 OpenAI 兼容性(含 SSE)
- 手工冒烟:真实注册 1 账号 → 网关真实对话 1 条验证全链路

## 17. 实施顺序(两阶段)

**阶段一(注册机)**:config → storage → mail_client → engine/browser → pool → api → web → 冒烟注册
**阶段二(网关)**:接口侦察 → trae_client → account_pool → adapter → 网关接口 → web 网关面板 → 冒烟对话

阶段一完成后即可开始阶段二;协议模式(engine/protocol.py)作为二期增强,不影响本计划交付。
