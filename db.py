from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from flask import g


@dataclass(frozen=True)
class DbConfig:
    path: Path


def _db_config() -> DbConfig:
    db_path = os.environ.get("APP_DB_PATH", "").strip()
    if db_path:
        return DbConfig(path=Path(db_path))
    return DbConfig(path=Path("data") / "app.db")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        cfg = _db_config()
        cfg.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(cfg.path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        g.db = conn
    return g.db


def close_db(_: Any = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db() -> None:
    cfg = _db_config()
    cfg.path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    schema = (Path(__file__).resolve().parent / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    _ensure_default_schedule(conn)
    conn.commit()
    conn.close()


def _ensure_default_schedule(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS c FROM schedule;").fetchone()["c"]
    if existing:
        return
    for weekday in range(7):
        conn.execute(
            """
            INSERT INTO schedule (weekday, is_open, start_time, end_time, max_seats)
            VALUES (?, 1, '18:00', '19:20', 20);
            """,
            (weekday,),
        )


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return get_db().execute(sql, tuple(params)).fetchone()


def query_all(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return get_db().execute(sql, tuple(params)).fetchall()
