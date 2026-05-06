from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .auth import hash_password, verify_password


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


@dataclass(frozen=True)
class User:
    username: str
    password_hash: str
    is_root: bool

    def public_dict(self) -> dict[str, object]:
        return {"username": self.username, "is_root": self.is_root}


class UserStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def bootstrap_root(self, username: str, password: str) -> None:
        if self.get_user(username) is not None:
            return
        self.create_user(username=username, password=password, is_root=True)

    def create_user(self, *, username: str, password: str, is_root: bool = False) -> User:
        username = username.strip()
        if not USERNAME_RE.match(username):
            raise ValueError("用户名只能包含 3-32 位字母、数字、下划线、点或短横线")
        if len(password) < 8:
            raise ValueError("密码至少需要 8 位")

        user = User(
            username=username,
            password_hash=hash_password(password),
            is_root=is_root,
        )
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users (username, password_hash, is_root)
                    VALUES (?, ?, ?)
                    """,
                    (user.username, user.password_hash, 1 if user.is_root else 0),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户已存在") from exc
        return user

    def get_user(self, username: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT username, password_hash, is_root
                FROM users
                WHERE username = ?
                """,
                (username,),
            ).fetchone()
        if row is None:
            return None
        return User(
            username=str(row["username"]),
            password_hash=str(row["password_hash"]),
            is_root=bool(row["is_root"]),
        )

    def verify_credentials(self, username: str, password: str) -> User | None:
        user = self.get_user(username)
        if user is None:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    def list_users(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT username, is_root
                FROM users
                ORDER BY is_root DESC, username ASC
                """
            ).fetchall()
        return [
            {"username": str(row["username"]), "is_root": bool(row["is_root"])}
            for row in rows
        ]

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    is_root INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn
