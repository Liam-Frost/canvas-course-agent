from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.table import Table

from .providers.canvas import CanvasClient
from .storage.sqlite import connect, list_courses, list_starred_course_ids, upsert_assignment, upsert_quiz

console = Console()


def sync_assignments(client: CanvasClient, *, db_path: str, days: int = 14, all_courses: bool = False) -> int:
    conn = connect(db_path)
    course_ids = [r["id"] for r in list_courses(conn)] if all_courses else list_starred_course_ids(conn)

    if not course_ids:
        console.print("No courses selected. Star some courses first: canvas-agent courses star ...")
        return 1

    now = datetime.now(UTC)
    end = now + timedelta(days=days)

    total = 0
    upcoming: list[tuple[str, str, str, str]] = []  # course_id, due_at, name, url

    with conn:
        for cid in course_ids:
            items = client.list_assignments(int(cid))
            total += len(items)
            for a in items:
                upsert_assignment(conn, int(cid), a)
                due = a.get("due_at")
                if not due:
                    continue
                try:
                    dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                except Exception:
                    continue
                if now <= dt <= end:
                    upcoming.append((str(cid), due, str(a.get("name") or ""), str(a.get("html_url") or "")))

    t = Table(title=f"Assignments synced: {total} (courses={len(course_ids)})")
    t.add_column("course")
    t.add_column("due_at")
    t.add_column("name")
    for row in sorted(upcoming, key=lambda x: x[1])[:50]:
        t.add_row(row[0], row[1], row[2])
    console.print(t)
    if len(upcoming) > 50:
        console.print(f"(showing 50/{len(upcoming)} upcoming within {days} days)")

    return 0


def sync_quizzes(client: CanvasClient, *, db_path: str, days: int = 14, all_courses: bool = False) -> int:
    conn = connect(db_path)
    course_ids = [r["id"] for r in list_courses(conn)] if all_courses else list_starred_course_ids(conn)

    if not course_ids:
        console.print("No courses selected. Star some courses first: canvas-agent courses star ...")
        return 1

    now = datetime.now(UTC)
    end = now + timedelta(days=days)

    total = 0
    upcoming: list[tuple[str, str, str, str]] = []  # course_id, due_at, title, url

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
                due = q.get("due_at")
                if not due:
                    continue
                try:
                    dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                except Exception:
                    continue
                if now <= dt <= end:
                    upcoming.append((str(cid), due, str(q.get("title") or ""), str(q.get("html_url") or "")))

    t = Table(title=f"Quizzes synced: {total} (courses={len(course_ids)})")
    t.add_column("course")
    t.add_column("due_at")
    t.add_column("title")
    for row in sorted(upcoming, key=lambda x: x[1])[:50]:
        t.add_row(row[0], row[1], row[2])
    console.print(t)
    if len(upcoming) > 50:
        console.print(f"(showing 50/{len(upcoming)} upcoming within {days} days)")

    return 0
