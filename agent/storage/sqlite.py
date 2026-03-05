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

CREATE TABLE IF NOT EXISTS course_people (
  course_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  name TEXT,
  sortable_name TEXT,
  short_name TEXT,
  login_id TEXT,
  sis_user_id TEXT,
  email TEXT,
  role TEXT,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (course_id, user_id, role)
);

CREATE TABLE IF NOT EXISTS course_modules (
  course_id INTEGER NOT NULL,
  module_id INTEGER NOT NULL,
  name TEXT,
  position INTEGER,
  unlock_at TEXT,
  state TEXT,
  items_count INTEGER,
  published INTEGER,
  require_sequential_progress INTEGER,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (course_id, module_id)
);

CREATE TABLE IF NOT EXISTS course_module_items (
  course_id INTEGER NOT NULL,
  module_id INTEGER NOT NULL,
  item_id INTEGER NOT NULL,
  title TEXT,
  type TEXT,
  content_id INTEGER,
  html_url TEXT,
  position INTEGER,
  published INTEGER,
  completion_requirement TEXT,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (course_id, module_id, item_id)
);

CREATE TABLE IF NOT EXISTS assignment_submissions (
  course_id INTEGER NOT NULL,
  assignment_id INTEGER NOT NULL,
  user_id INTEGER,
  workflow_state TEXT,
  submitted_at TEXT,
  graded_at TEXT,
  score REAL,
  grade TEXT,
  attempt INTEGER,
  late INTEGER,
  missing INTEGER,
  excused INTEGER,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (course_id, assignment_id)
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


def replace_course_people(conn: sqlite3.Connection, course_id: int, people: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM course_people WHERE course_id=?", (course_id,))
    for p in people:
        role = ""
        enr = p.get("enrollments") or []
        if isinstance(enr, list) and enr:
            role = str((enr[0] or {}).get("type") or "")

        conn.execute(
            """
            INSERT OR REPLACE INTO course_people (
              course_id, user_id, name, sortable_name, short_name, login_id, sis_user_id, email, role, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                p.get("id"),
                p.get("name"),
                p.get("sortable_name"),
                p.get("short_name"),
                p.get("login_id"),
                p.get("sis_user_id"),
                p.get("email"),
                role,
                json.dumps(p, ensure_ascii=False),
            ),
        )


def replace_course_modules(conn: sqlite3.Connection, course_id: int, modules: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM course_module_items WHERE course_id=?", (course_id,))
    conn.execute("DELETE FROM course_modules WHERE course_id=?", (course_id,))

    for m in modules:
        module_id = m.get("id")
        conn.execute(
            """
            INSERT INTO course_modules (
              course_id, module_id, name, position, unlock_at, state, items_count, published,
              require_sequential_progress, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                module_id,
                m.get("name"),
                m.get("position"),
                m.get("unlock_at"),
                m.get("state"),
                m.get("items_count"),
                1 if m.get("published") else 0,
                1 if m.get("require_sequential_progress") else 0,
                json.dumps(m, ensure_ascii=False),
            ),
        )

        items = m.get("items") or []
        for it in items:
            conn.execute(
                """
                INSERT INTO course_module_items (
                  course_id, module_id, item_id, title, type, content_id, html_url, position,
                  published, completion_requirement, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    course_id,
                    module_id,
                    it.get("id"),
                    it.get("title"),
                    it.get("type"),
                    it.get("content_id"),
                    it.get("html_url"),
                    it.get("position"),
                    1 if it.get("published") else 0,
                    json.dumps(it.get("completion_requirement"), ensure_ascii=False)
                    if it.get("completion_requirement") is not None
                    else None,
                    json.dumps(it, ensure_ascii=False),
                ),
            )


def upsert_assignment_submission(conn: sqlite3.Connection, course_id: int, assignment_id: int, s: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO assignment_submissions (
          course_id, assignment_id, user_id, workflow_state, submitted_at, graded_at,
          score, grade, attempt, late, missing, excused, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(course_id, assignment_id) DO UPDATE SET
          user_id=excluded.user_id,
          workflow_state=excluded.workflow_state,
          submitted_at=excluded.submitted_at,
          graded_at=excluded.graded_at,
          score=excluded.score,
          grade=excluded.grade,
          attempt=excluded.attempt,
          late=excluded.late,
          missing=excluded.missing,
          excused=excluded.excused,
          raw_json=excluded.raw_json,
          updated_at_local=datetime('now');
        """,
        (
            course_id,
            assignment_id,
            s.get("user_id"),
            s.get("workflow_state"),
            s.get("submitted_at"),
            s.get("graded_at"),
            s.get("score"),
            s.get("grade"),
            s.get("attempt"),
            1 if s.get("late") else 0,
            1 if s.get("missing") else 0,
            1 if s.get("excused") else 0,
            json.dumps(s, ensure_ascii=False),
        ),
    )
