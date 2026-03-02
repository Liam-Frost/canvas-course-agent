from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.table import Table

from .providers.canvas import CanvasClient
from .storage.sqlite import (
    connect,
    list_starred_course_ids,
    upsert_assignment,
    upsert_calendar_item,
    upsert_course,
    upsert_quiz,
)
from .timeutil import fmt_canvas_dt_2line, get_tz, tz_label

console = Console()


def sync_courses(client: CanvasClient, *, db_path: str) -> int:
    courses = client.list_courses(include_syllabus=True)

    conn = connect(db_path)
    with conn:
        for c in courses:
            upsert_course(conn, c)

    t = Table(title=f"Courses synced: {len(courses)}")
    t.add_column("id", justify="right")
    t.add_column("code")
    t.add_column("name")
    t.add_column("term")
    for c in courses[:30]:
        t.add_row(
            str(c.get("id")),
            str(c.get("course_code") or ""),
            str(c.get("name") or ""),
            str((c.get("term") or {}).get("name") or ""),
        )

    console.print(t)
    if len(courses) > 30:
        console.print(f"(showing 30/{len(courses)})")

    return 0


def sync_calendar(
    client: CanvasClient,
    *,
    db_path: str,
    days: int = 14,
    all_courses: bool = False,
    type: str | None = None,
    timezone: str = "UTC",
) -> int:
    now = datetime.now(UTC)
    start = now.isoformat()
    end = (now + timedelta(days=days)).isoformat()

    context_codes = None
    if not all_courses:
        conn0 = connect(db_path)
        starred = list_starred_course_ids(conn0)
        context_codes = [f"course_{cid}" for cid in starred]

    items = client.list_calendar_events(start_date=start, end_date=end, type=type, context_codes=context_codes)

    conn = connect(db_path)
    with conn:
        for it in items:
            upsert_calendar_item(conn, it)

    tz = get_tz(timezone)
    tzs = tz_label(tz)

    t = Table(title=f"Calendar items synced: {len(items)} (next {days} days)")
    t.add_column("id", justify="right")
    t.add_column("type")
    t.add_column("title")
    t.add_column(f"start_at({tzs})")
    t.add_column("context")

    for it in sorted(items, key=lambda x: x.get("start_at") or "")[:50]:
        t.add_row(
            str(it.get("id")),
            str(it.get("type") or ""),
            str(it.get("title") or ""),
            fmt_canvas_dt_2line(it.get("start_at"), tz),
            str(it.get("context_code") or ""),
        )

    console.print(t)
    if len(items) > 50:
        console.print(f"(showing 50/{len(items)})")

    return 0
