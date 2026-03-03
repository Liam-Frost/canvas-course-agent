from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
  id INTEGER PRIMARY KEY,
  name TEXT,
  course_code TEXT,
  workflow_state TEXT,
  start_at TEXT,
  end_at TEXT,
  term_name TEXT,
  syllabus_body TEXT,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS calendar_items (
  id INTEGER PRIMARY KEY,
  title TEXT,
  type TEXT,
  start_at TEXT,
  end_at TEXT,
  all_day INTEGER,
  context_code TEXT,
  html_url TEXT,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS starred_courses (
  course_id INTEGER PRIMARY KEY,
  starred_at_local TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assignments (
  id INTEGER PRIMARY KEY,
  course_id INTEGER,
  name TEXT,
  due_at TEXT,
  unlock_at TEXT,
  lock_at TEXT,
  html_url TEXT,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quizzes (
  id INTEGER PRIMARY KEY,
  course_id INTEGER,
  title TEXT,
  due_at TEXT,
  unlock_at TEXT,
  lock_at TEXT,
  html_url TEXT,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications_sent (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  item_id INTEGER NOT NULL,
  channel TEXT NOT NULL,
  remind_at TEXT NOT NULL,
  sent_at_local TEXT DEFAULT (datetime('now')),
  UNIQUE(kind, item_id, channel, remind_at)
);

CREATE TABLE IF NOT EXISTS custom_reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  at_utc TEXT NOT NULL,
  channels TEXT NOT NULL, -- comma separated: discord,telegram
  silent INTEGER DEFAULT 0,
  enabled INTEGER DEFAULT 1,
  created_at_local TEXT DEFAULT (datetime('now'))
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_course(conn: sqlite3.Connection, course: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO courses (
          id, name, course_code, workflow_state, start_at, end_at, term_name, syllabus_body, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          name=excluded.name,
          course_code=excluded.course_code,
          workflow_state=excluded.workflow_state,
          start_at=excluded.start_at,
          end_at=excluded.end_at,
          term_name=excluded.term_name,
          syllabus_body=excluded.syllabus_body,
          raw_json=excluded.raw_json,
          updated_at_local=datetime('now');
        """,
        (
            course.get("id"),
            course.get("name"),
            course.get("course_code"),
            course.get("workflow_state"),
            course.get("start_at"),
            course.get("end_at"),
            (course.get("term") or {}).get("name"),
            course.get("syllabus_body"),
            json.dumps(course, ensure_ascii=False),
        ),
    )


def upsert_calendar_item(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO calendar_items (
          id, title, type, start_at, end_at, all_day, context_code, html_url, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          type=excluded.type,
          start_at=excluded.start_at,
          end_at=excluded.end_at,
          all_day=excluded.all_day,
          context_code=excluded.context_code,
          html_url=excluded.html_url,
          raw_json=excluded.raw_json,
          updated_at_local=datetime('now');
        """,
        (
            item.get("id"),
            item.get("title"),
            item.get("type"),
            item.get("start_at"),
            item.get("end_at"),
            1 if item.get("all_day") else 0,
            item.get("context_code"),
            item.get("html_url"),
            json.dumps(item, ensure_ascii=False),
        ),
    )


def is_starred(conn: sqlite3.Connection, course_id: int) -> bool:
    r = conn.execute("SELECT 1 FROM starred_courses WHERE course_id=?", (course_id,)).fetchone()
    return r is not None


def list_courses(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT id, name, course_code, term_name FROM courses ORDER BY term_name, course_code, name"
        ).fetchall()
    )


def list_starred_course_ids(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT course_id FROM starred_courses ORDER BY course_id").fetchall()]


def star_course(conn: sqlite3.Connection, course_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO starred_courses (course_id) VALUES (?)",
        (course_id,),
    )


def unstar_course(conn: sqlite3.Connection, course_id: int) -> None:
    conn.execute("DELETE FROM starred_courses WHERE course_id=?", (course_id,))


def upsert_assignment(conn: sqlite3.Connection, course_id: int, a: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO assignments (id, course_id, name, due_at, unlock_at, lock_at, html_url, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          course_id=excluded.course_id,
          name=excluded.name,
          due_at=excluded.due_at,
          unlock_at=excluded.unlock_at,
          lock_at=excluded.lock_at,
          html_url=excluded.html_url,
          raw_json=excluded.raw_json,
          updated_at_local=datetime('now');
        """,
        (
            a.get("id"),
            course_id,
            a.get("name"),
            a.get("due_at"),
            a.get("unlock_at"),
            a.get("lock_at"),
            a.get("html_url"),
            json.dumps(a, ensure_ascii=False),
        ),
    )


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return (r[0] if r else default)


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at_local=datetime('now');
        """,
        (key, value),
    )


def upsert_quiz(conn: sqlite3.Connection, course_id: int, q: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO quizzes (id, course_id, title, due_at, unlock_at, lock_at, html_url, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          course_id=excluded.course_id,
          title=excluded.title,
          due_at=excluded.due_at,
          unlock_at=excluded.unlock_at,
          lock_at=excluded.lock_at,
          html_url=excluded.html_url,
          raw_json=excluded.raw_json,
          updated_at_local=datetime('now');
        """,
        (
            q.get("id"),
            course_id,
            q.get("title"),
            q.get("due_at"),
            q.get("unlock_at"),
            q.get("lock_at"),
            q.get("html_url"),
            json.dumps(q, ensure_ascii=False),
        ),
    )
