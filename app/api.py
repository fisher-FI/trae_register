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
