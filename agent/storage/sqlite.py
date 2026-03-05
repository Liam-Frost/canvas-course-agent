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

CREATE TABLE IF NOT EXISTS course_announcements (
  course_id INTEGER NOT NULL,
  announcement_id INTEGER NOT NULL,
  title TEXT,
  posted_at TEXT,
  delayed_post_at TEXT,
  html_url TEXT,
  message TEXT,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (course_id, announcement_id)
);

CREATE TABLE IF NOT EXISTS course_pages (
  course_id INTEGER NOT NULL,
  page_id INTEGER NOT NULL,
  url TEXT,
  title TEXT,
  html_url TEXT,
  published INTEGER,
  editing_roles TEXT,
  updated_at TEXT,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (course_id, page_id)
);

CREATE TABLE IF NOT EXISTS course_files (
  course_id INTEGER NOT NULL,
  file_id INTEGER NOT NULL,
  display_name TEXT,
  filename TEXT,
  content_type TEXT,
  size INTEGER,
  modified_at TEXT,
  url TEXT,
  folder_id INTEGER,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (course_id, file_id)
);

CREATE TABLE IF NOT EXISTS course_discussions (
  course_id INTEGER NOT NULL,
  topic_id INTEGER NOT NULL,
  title TEXT,
  posted_at TEXT,
  last_reply_at TEXT,
  html_url TEXT,
  discussion_type TEXT,
  locked INTEGER,
  raw_json TEXT NOT NULL,
  updated_at_local TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (course_id, topic_id)
);

CREATE TABLE IF NOT EXISTS ai_task_mapping_raw (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  item_id INTEGER NOT NULL,
  course_id INTEGER,
  candidate_topic TEXT,
  confidence REAL,
  evidence TEXT,
  model_version TEXT,
  raw_json TEXT NOT NULL,
  generated_at_utc TEXT NOT NULL,
  UNIQUE(kind, item_id, candidate_topic, generated_at_utc)
);

CREATE TABLE IF NOT EXISTS ai_task_mapping_resolved (
  kind TEXT NOT NULL,
  item_id INTEGER NOT NULL,
  course_id INTEGER,
  primary_topic TEXT,
  alternatives_json TEXT,
  confidence REAL,
  evidence TEXT,
  source TEXT NOT NULL, -- ai|manual
  model_version TEXT,
  updated_at_utc TEXT NOT NULL,
  PRIMARY KEY (kind, item_id)
);

CREATE TABLE IF NOT EXISTS ai_task_mapping_override (
  kind TEXT NOT NULL,
  item_id INTEGER NOT NULL,
  course_id INTEGER,
  topic TEXT NOT NULL,
  note TEXT,
  updated_at_utc TEXT NOT NULL,
  PRIMARY KEY (kind, item_id)
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


def replace_course_announcements(conn: sqlite3.Connection, course_id: int, items: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM course_announcements WHERE course_id=?", (course_id,))
    for a in items:
        conn.execute(
            """
            INSERT OR REPLACE INTO course_announcements (
              course_id, announcement_id, title, posted_at, delayed_post_at, html_url, message, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                a.get("id"),
                a.get("title"),
                a.get("posted_at"),
                a.get("delayed_post_at"),
                a.get("html_url"),
                a.get("message"),
                json.dumps(a, ensure_ascii=False),
            ),
        )


def replace_course_pages(conn: sqlite3.Connection, course_id: int, items: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM course_pages WHERE course_id=?", (course_id,))
    for p in items:
        conn.execute(
            """
            INSERT OR REPLACE INTO course_pages (
              course_id, page_id, url, title, html_url, published, editing_roles, updated_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                p.get("page_id"),
                p.get("url"),
                p.get("title"),
                p.get("html_url"),
                1 if p.get("published") else 0,
                p.get("editing_roles"),
                p.get("updated_at"),
                json.dumps(p, ensure_ascii=False),
            ),
        )


def replace_course_files(conn: sqlite3.Connection, course_id: int, items: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM course_files WHERE course_id=?", (course_id,))
    for f in items:
        conn.execute(
            """
            INSERT OR REPLACE INTO course_files (
              course_id, file_id, display_name, filename, content_type, size, modified_at, url, folder_id, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                f.get("id"),
                f.get("display_name"),
                f.get("filename"),
                f.get("content-type") or f.get("content_type"),
                f.get("size"),
                f.get("modified_at"),
                f.get("url"),
                f.get("folder_id"),
                json.dumps(f, ensure_ascii=False),
            ),
        )


def replace_course_discussions(conn: sqlite3.Connection, course_id: int, items: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM course_discussions WHERE course_id=?", (course_id,))
    for d in items:
        conn.execute(
            """
            INSERT OR REPLACE INTO course_discussions (
              course_id, topic_id, title, posted_at, last_reply_at, html_url, discussion_type, locked, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                d.get("id"),
                d.get("title"),
                d.get("posted_at"),
                d.get("last_reply_at"),
                d.get("html_url"),
                d.get("discussion_type"),
                1 if d.get("locked") else 0,
                json.dumps(d, ensure_ascii=False),
            ),
        )


def upsert_ai_mapping_raw(
    conn: sqlite3.Connection,
    *,
    kind: str,
    item_id: int,
    course_id: int | None,
    candidate_topic: str,
    confidence: float | None,
    evidence: str | None,
    model_version: str | None,
    raw_obj: dict[str, Any],
    generated_at_utc: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO ai_task_mapping_raw (
          kind, item_id, course_id, candidate_topic, confidence, evidence, model_version, raw_json, generated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kind,
            item_id,
            course_id,
            candidate_topic,
            confidence,
            evidence,
            model_version,
            json.dumps(raw_obj, ensure_ascii=False),
            generated_at_utc,
        ),
    )


def upsert_ai_mapping_resolved(
    conn: sqlite3.Connection,
    *,
    kind: str,
    item_id: int,
    course_id: int | None,
    primary_topic: str | None,
    alternatives: list[str],
    confidence: float | None,
    evidence: str | None,
    source: str,
    model_version: str | None,
    updated_at_utc: str,
) -> None:
    conn.execute(
        """
        INSERT INTO ai_task_mapping_resolved (
          kind, item_id, course_id, primary_topic, alternatives_json, confidence, evidence, source, model_version, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(kind, item_id) DO UPDATE SET
          course_id=excluded.course_id,
          primary_topic=excluded.primary_topic,
          alternatives_json=excluded.alternatives_json,
          confidence=excluded.confidence,
          evidence=excluded.evidence,
          source=excluded.source,
          model_version=excluded.model_version,
          updated_at_utc=excluded.updated_at_utc;
        """,
        (
            kind,
            item_id,
            course_id,
            primary_topic,
            json.dumps(alternatives, ensure_ascii=False),
            confidence,
            evidence,
            source,
            model_version,
            updated_at_utc,
        ),
    )


def get_ai_mapping_override(conn: sqlite3.Connection, *, kind: str, item_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT topic, note FROM ai_task_mapping_override WHERE kind=? AND item_id=?",
        (kind, item_id),
    ).fetchone()
