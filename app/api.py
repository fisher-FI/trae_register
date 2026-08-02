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
        batch_id = f"batch-{int(__import__('time').time())}"
        # 领邮箱 → 建任务 → 后台执行
        app.state.leases: dict[str, str] = getattr(app.state, "leases", {})
        tasks_created = []
        for i in range(req.count):
            try:
                mb = app.state.mail.reserve("trae", f"{batch_id}-w{i+1}-a1",
                                            cfg.lease_seconds)
            except NoMailboxError:
                break
            task_id = storage.create_task(batch_id, mb.email, "browser")
            app.state.leases[mb.email] = mb.lease_token
            tasks_created.append((task_id, mb.email))
        if not tasks_created:
            raise HTTPException(503, "邮箱池无可用邮箱(no_available)")
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
                async with BrowserEngine(app.state.cfg,
                                         ProxyManager(app.state.cfg)) as eng:
                    lease_token = app.state.leases.get(email, "")

                    async def code_provider(mail_addr):
                        if not lease_token:
                            return None
                        try:
                            return app.state.mail.wait_for_code(
                                mail_addr, lease_token,
                                timeout=app.state.cfg.code_timeout,
                                interval=app.state.cfg.code_poll_interval)
                        except TimeoutError:
                            return None

                    result = await eng.run_full(
                        email, f"{batch_id}-t{task_id}", code_provider)
                if result.ok:
                    storage.update_task_status(task_id, "success")
                    storage.create_account(
                        email=result.email, password=result.password,
                        engine="browser",
                        cookie=result.credentials.get("cookie", ""),
                        access_token=result.credentials.get("access_token", ""),
                        refresh_token=result.credentials.get("refresh_token", ""),
                        health_status="healthy",
                    )
                    app.state.mail.mark_used(
                        email, app.state.leases.get(email, ""),
                        platform="trae", login_email=email)
                else:
                    storage.update_task_status(task_id, "failed",
                                               reason=result.reason)
                    try:
                        app.state.mail.release(
                            email, app.state.leases.get(email, ""),
                            platform="trae",
                            reason=f"register failed: {result.reason[:100]}")
                    except Exception:
                        pass
            except Exception as e:  # noqa: BLE001
                storage.update_task_status(task_id, "failed", reason=str(e))
            await _notify(app, task_id, email)

        pool = TaskPool(concurrency=app.state.cfg.concurrency)
        await pool.submit_batch(tasks, job)

    async def _notify(app, task_id, email):
        task = storage.get_task(task_id)
        payload = {"type": "task", "task": task}
        for ws in list(app.state.connections):
            try:
                await ws.send_json(payload)
            except Exception:
                pass

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
