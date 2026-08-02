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
