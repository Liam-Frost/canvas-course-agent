from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.table import Table

from .providers.canvas import CanvasClient
from .storage.sqlite import connect, list_courses, list_starred_course_ids, upsert_assignment, upsert_quiz
from .timeutil import fmt_canvas_dt, get_tz, tz_label, parse_canvas_dt

console = Console()


def sync_assignments(
    client: CanvasClient,
    *,
    db_path: str,
    days: int = 14,
    all_courses: bool = False,
    timezone: str = "UTC",
) -> int:
    conn = connect(db_path)
    course_rows = list_courses(conn)
    course_name_by_id = {int(r["id"]): str(r["name"] or r["course_code"] or r["id"]) for r in course_rows}

    course_ids = [r["id"] for r in course_rows] if all_courses else list_starred_course_ids(conn)

    if not course_ids:
        console.print("No courses selected. Star some courses first: canvas-agent courses star ...")
        return 1

    tz = get_tz(timezone)
    tzs = tz_label(tz)

    now = datetime.now(UTC)
    end = now + timedelta(days=days)

    total = 0
    upcoming: list[tuple[str, str, str, str]] = []  # course_name, due_at, name, url

    with conn:
        for cid in course_ids:
            items = client.list_assignments(int(cid))
            total += len(items)
            for a in items:
                upsert_assignment(conn, int(cid), a)
                due = a.get("due_at")
                if not due:
                    continue
                dt = parse_canvas_dt(due)
                if not dt:
                    continue
                if now <= dt <= end:
                    upcoming.append(
                        (
                            course_name_by_id.get(int(cid), str(cid)),
                            due,
                            str(a.get("name") or ""),
                            str(a.get("html_url") or ""),
                        )
                    )

    t = Table(title=f"Assignments synced: {total} (courses={len(course_ids)})")
    t.add_column("course")
    t.add_column("name")
    t.add_column(f"due_at({tzs})")
    for row in sorted(upcoming, key=lambda x: x[1])[:50]:
        t.add_row(row[0], row[2], fmt_canvas_dt(row[1], tz))
    console.print(t)
    if len(upcoming) > 50:
        console.print(f"(showing 50/{len(upcoming)} upcoming within {days} days)")

    return 0


def sync_quizzes(
    client: CanvasClient,
    *,
    db_path: str,
    days: int = 14,
    all_courses: bool = False,
    timezone: str = "UTC",
) -> int:
    conn = connect(db_path)
    course_rows = list_courses(conn)
    course_name_by_id = {int(r["id"]): str(r["name"] or r["course_code"] or r["id"]) for r in course_rows}

    course_ids = [r["id"] for r in course_rows] if all_courses else list_starred_course_ids(conn)

    if not course_ids:
        console.print("No courses selected. Star some courses first: canvas-agent courses star ...")
        return 1

    tz = get_tz(timezone)
    tzs = tz_label(tz)

    now = datetime.now(UTC)
    end = now + timedelta(days=days)

    total = 0
    upcoming: list[tuple[str, str, str, str, int | None]] = []  # course_name, unlock_at, title, due_at, time_limit(min)

    with conn:
        for cid in course_ids:
            try:
                items = client.list_quizzes(int(cid))
            except Exception as e:
                # Canvas returns 404 for /quizzes when the Quizzes feature is disabled for a course.
                # Don't fail the whole sync.
                console.print(f"[yellow]Skip quizzes for course {cid}: {type(e).__name__}[/yellow]")
                continue

            total += len(items)
            for q in items:
                upsert_quiz(conn, int(cid), q)
                unlock = q.get("unlock_at")
                due = q.get("due_at")
                time_limit = q.get("time_limit")

                # Prefer unlock_at as "start" for exams/quizzes; fall back to due_at.
                ref = unlock or due
                if not ref:
                    continue
                dt = parse_canvas_dt(ref)
                if not dt:
                    continue
                if now <= dt <= end:
                    upcoming.append(
                        (
                            course_name_by_id.get(int(cid), str(cid)),
                            str(unlock or ""),
                            str(q.get("title") or ""),
                            str(due or ""),
                            int(time_limit) if time_limit is not None else None,
                        )
                    )

    t = Table(title=f"Quizzes synced: {total} (courses={len(course_ids)})")
    t.add_column("course")
    t.add_column("title")
    t.add_column(f"start_at({tzs})")
    t.add_column("duration(min)")
    t.add_column(f"due_at({tzs})")

    def _sort_key(r: tuple[str, str, str, str, int | None]) -> str:
        # sort by start_at (unlock) first, else due
        return r[1] or r[3]

    for row in sorted(upcoming, key=_sort_key)[:50]:
        course, unlock_at, title, due_at, time_limit = row
        t.add_row(
            course,
            title,
            fmt_canvas_dt(unlock_at, tz),
            "" if time_limit is None else str(time_limit),
            fmt_canvas_dt(due_at, tz),
        )
    console.print(t)
    if len(upcoming) > 50:
        console.print(f"(showing 50/{len(upcoming)} upcoming within {days} days)")

    return 0
