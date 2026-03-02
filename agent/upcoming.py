from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from rich.console import Console
from rich.table import Table

from .storage.sqlite import connect, list_courses, list_starred_course_ids
from .timeutil import fmt_canvas_dt, get_tz, parse_canvas_dt, tz_label

console = Console()


@dataclass
class Item:
    kind: str  # assignment|quiz
    course_id: int
    course_name: str
    title: str
    start_at: str  # canvas iso
    due_at: str  # canvas iso
    duration_min: int | None
    url: str


def _course_name_map(conn: sqlite3.Connection) -> dict[int, str]:
    rows = list_courses(conn)
    return {int(r["id"]): str(r["name"] or r["course_code"] or r["id"]) for r in rows}


def upcoming(*, db_path: str, days: int = 14, all_courses: bool = False, timezone: str = "UTC") -> int:
    conn = connect(db_path)
    course_name_by_id = _course_name_map(conn)
    course_ids = [int(r["id"]) for r in list_courses(conn)] if all_courses else list_starred_course_ids(conn)

    if not course_ids:
        console.print("No courses selected. Star some courses first: canvas-agent courses star ...")
        return 1

    tz = get_tz(timezone)
    tzs = tz_label(tz)

    now = datetime.now(UTC)
    end = now + timedelta(days=days)

    # Load quizzes first to build dedupe set for quizzes that are actually assignments.
    quiz_rows = conn.execute(
        "SELECT course_id, title, due_at, unlock_at, lock_at, html_url, raw_json FROM quizzes WHERE course_id IN (%s)"
        % ",".join("?" * len(course_ids)),
        course_ids,
    ).fetchall()

    assignment_ids_from_quizzes: set[int] = set()
    items: list[Item] = []

    for r in quiz_rows:
        raw: dict[str, Any] = json.loads(r["raw_json"])
        if raw.get("quiz_type") == "assignment" and raw.get("assignment_id"):
            try:
                assignment_ids_from_quizzes.add(int(raw["assignment_id"]))
            except Exception:
                pass

        ref = raw.get("unlock_at") or raw.get("due_at")
        dt = parse_canvas_dt(ref)
        if not dt or not (now <= dt <= end):
            continue

        items.append(
            Item(
                kind="quiz",
                course_id=int(r["course_id"]),
                course_name=course_name_by_id.get(int(r["course_id"]), str(r["course_id"])),
                title=str(r["title"] or ""),
                start_at=str(raw.get("unlock_at") or ""),
                due_at=str(raw.get("due_at") or ""),
                duration_min=(int(raw["time_limit"]) if raw.get("time_limit") is not None else None),
                url=str(raw.get("html_url") or ""),
            )
        )

    # Assignments (skip ones that are represented by quizzes-as-assignments)
    asg_rows = conn.execute(
        "SELECT id, course_id, name, due_at, unlock_at, lock_at, html_url, raw_json FROM assignments WHERE course_id IN (%s)"
        % ",".join("?" * len(course_ids)),
        course_ids,
    ).fetchall()

    for r in asg_rows:
        asg_id = int(r["id"])
        if asg_id in assignment_ids_from_quizzes:
            continue

        dt = parse_canvas_dt(r["due_at"])
        if not dt or not (now <= dt <= end):
            continue

        items.append(
            Item(
                kind="assignment",
                course_id=int(r["course_id"]),
                course_name=course_name_by_id.get(int(r["course_id"]), str(r["course_id"])),
                title=str(r["name"] or ""),
                start_at=str(r["unlock_at"] or ""),
                due_at=str(r["due_at"] or ""),
                duration_min=None,
                url=str(r["html_url"] or ""),
            )
        )

    def _sort_key(it: Item) -> datetime:
        return parse_canvas_dt(it.start_at) or parse_canvas_dt(it.due_at) or datetime.max.replace(tzinfo=UTC)

    items.sort(key=_sort_key)

    t = Table(title=f"Upcoming (next {days} days)")
    t.add_column("course")
    t.add_column("type")
    t.add_column("title")
    t.add_column(f"start_at({tzs})")
    t.add_column("duration(min)")
    t.add_column(f"due_at({tzs})")

    for it in items[:80]:
        t.add_row(
            it.course_name,
            it.kind,
            it.title,
            fmt_canvas_dt(it.start_at, tz),
            "" if it.duration_min is None else str(it.duration_min),
            fmt_canvas_dt(it.due_at, tz),
        )

    console.print(t)
    if len(items) > 80:
        console.print(f"(showing 80/{len(items)})")

    return 0
