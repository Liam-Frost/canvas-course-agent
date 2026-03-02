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
