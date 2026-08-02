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
