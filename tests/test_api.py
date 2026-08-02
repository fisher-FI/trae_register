import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Config
from app.storage import Storage


@pytest.fixture
def client(tmp_path):
    storage = Storage(tmp_path / "t.db")
    # 显式空 key,避免读到项目 .env 中的真实 key
    app = create_app(storage=storage, concurrency=2,
                     cfg=Config(mailops_api_key=""))
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
