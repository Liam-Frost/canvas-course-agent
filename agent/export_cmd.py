from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rich.console import Console

from .storage.sqlite import connect, list_courses, list_starred_course_ids
from .timeutil import parse_canvas_dt

console = Console()


@dataclass
class Event:
    uid: str
    summary: str
    dtstart: datetime
    dtend: datetime
    description: str
    url: str


def _escape_ics(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fmt_dt_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _course_name_map(conn) -> dict[int, str]:
    rows = list_courses(conn)
    return {int(r["id"]): str(r["name"] or r["course_code"] or r["id"]) for r in rows}


def export_ics(*, db_path: str, out_path: str = "./export/canvas.ics", days: int = 30, all_courses: bool = False) -> int:
    conn = connect(db_path)
    course_name_by_id = _course_name_map(conn)
    course_ids = [int(r["id"]) for r in list_courses(conn)] if all_courses else list_starred_course_ids(conn)
    if not course_ids:
        console.print("No courses selected. Star some courses first: canvas-agent courses star ...")
        return 1

    now = datetime.now(UTC)
    end = now + timedelta(days=days)

    # Build dedupe set: quizzes that map to assignments
    quiz_rows = conn.execute(
        "SELECT course_id, raw_json FROM quizzes WHERE course_id IN (%s)" % ",".join("?" * len(course_ids)),
        course_ids,
    ).fetchall()
    assignment_ids_from_quizzes: set[int] = set()
    quizzes: list[tuple[int, dict[str, Any]]] = []
    for r in quiz_rows:
        raw = json.loads(r["raw_json"])
        if raw.get("quiz_type") == "assignment" and raw.get("assignment_id"):
            try:
                assignment_ids_from_quizzes.add(int(raw["assignment_id"]))
            except Exception:
                pass
        quizzes.append((int(r["course_id"]), raw))

    events: list[Event] = []

    # Quizzes: use unlock_at as start when present; else due_at.
    for cid, q in quizzes:
        if cid not in course_ids:
            continue

        start = parse_canvas_dt(q.get("unlock_at") or q.get("due_at"))
        if not start or not (now <= start <= end):
            continue

        # End: prefer lock_at; else start + time_limit minutes (derived); else due_at.
        lock = parse_canvas_dt(q.get("lock_at"))
        due = parse_canvas_dt(q.get("due_at"))
        time_limit = q.get("time_limit")
        if lock:
            dtend = lock
        elif time_limit is not None:
            try:
                dtend = start + timedelta(minutes=int(time_limit))
            except Exception:
                dtend = (due or start)
        else:
            dtend = (due or start)

        title = str(q.get("title") or "Quiz")
        course = course_name_by_id.get(cid, str(cid))
        url = str(q.get("html_url") or "")
        desc = f"Course: {course}\nType: quiz\n"
        if q.get("time_limit") is not None:
            desc += f"Time limit (min): {q.get('time_limit')}\n"
        if url:
            desc += f"URL: {url}\n"

        events.append(
            Event(
                uid=f"canvas-quiz-{q.get('id')}@canvas-course-agent",
                summary=f"{course} — {title}",
                dtstart=start,
                dtend=dtend,
                description=desc,
                url=url,
            )
        )

    # Assignments
    asg_rows = conn.execute(
        "SELECT id, course_id, name, due_at, html_url, raw_json FROM assignments WHERE course_id IN (%s)" % ",".join("?" * len(course_ids)),
        course_ids,
    ).fetchall()
    for r in asg_rows:
        asg_id = int(r["id"])
        if asg_id in assignment_ids_from_quizzes:
            continue
        due = parse_canvas_dt(r["due_at"])
        if not due or not (now <= due <= end):
            continue

        cid = int(r["course_id"])
        course = course_name_by_id.get(cid, str(cid))
        title = str(r["name"] or "Assignment")
        url = str(r["html_url"] or "")
        desc = f"Course: {course}\nType: assignment\n"
        if url:
            desc += f"URL: {url}\n"

        # Assignments are point-in-time reminders; set end = start + 15min for calendar display.
        dtstart = due
        dtend = due + timedelta(minutes=15)

        events.append(
            Event(
                uid=f"canvas-asg-{asg_id}@canvas-course-agent",
                summary=f"{course} — {title} (due)",
                dtstart=dtstart,
                dtend=dtend,
                description=desc,
                url=url,
            )
        )

    events.sort(key=lambda e: e.dtstart)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append("PRODID:-//canvas-course-agent//EN")
    lines.append("CALSCALE:GREGORIAN")

    dtstamp = _fmt_dt_utc(datetime.now(UTC))
    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{_escape_ics(ev.uid)}")
        lines.append(f"DTSTAMP:{dtstamp}")
        lines.append(f"DTSTART:{_fmt_dt_utc(ev.dtstart)}")
        lines.append(f"DTEND:{_fmt_dt_utc(ev.dtend)}")
        lines.append(f"SUMMARY:{_escape_ics(ev.summary)}")
        if ev.url:
            lines.append(f"URL:{_escape_ics(ev.url)}")
        if ev.description:
            lines.append(f"DESCRIPTION:{_escape_ics(ev.description)}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    out.write_text("\r\n".join(lines) + "\r\n")

    console.print(f"Wrote ICS: {out} (events={len(events)})")
    return 0


def export_md(*, db_path: str, out_dir: str = "./export/md", days: int = 30, all_courses: bool = False) -> int:
    conn = connect(db_path)
    course_ids = [int(r["id"]) for r in list_courses(conn)] if all_courses else list_starred_course_ids(conn)
    if not course_ids:
        console.print("No courses selected. Star some courses first: canvas-agent courses star ...")
        return 1

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # courses table already has syllabus_body raw html; we just save a stub + upcoming list.
    now = datetime.now(UTC)
    end = now + timedelta(days=days)

    for cid in course_ids:
        course = conn.execute(
            "SELECT id, name, course_code, term_name, syllabus_body FROM courses WHERE id=?",
            (cid,),
        ).fetchone()
        if not course:
            continue

        safe_name = (course["course_code"] or str(cid)).replace("/", "-").replace(" ", "_")
        path = out / f"{safe_name}.md"

        lines: list[str] = []
        lines.append(f"# {course['name']}")
        lines.append("")
        lines.append(f"- course_id: {cid}")
        lines.append(f"- term: {course['term_name']}")
        lines.append("")

        # Upcoming assignments
        lines.append(f"## Upcoming (next {days} days)")
        lines.append("")

        asg_rows = conn.execute(
            "SELECT name, due_at, html_url FROM assignments WHERE course_id=?",
            (cid,),
        ).fetchall()
        for r in asg_rows:
            due = parse_canvas_dt(r["due_at"])
            if not due or not (now <= due <= end):
                continue
            url = r["html_url"] or ""
            title = r["name"] or "(untitled)"
            lines.append(f"- **Assignment**: {title} — due `{r['due_at']}` {url}")

        quiz_rows = conn.execute(
            "SELECT title, raw_json FROM quizzes WHERE course_id=?",
            (cid,),
        ).fetchall()
        for r in quiz_rows:
            raw = json.loads(r["raw_json"])
            ref = raw.get("unlock_at") or raw.get("due_at")
            dt = parse_canvas_dt(ref)
            if not dt or not (now <= dt <= end):
                continue
            url = raw.get("html_url") or ""
            title = raw.get("title") or "(untitled quiz)"
            lines.append(f"- **Quiz**: {title} — start `{raw.get('unlock_at') or ''}` due `{raw.get('due_at') or ''}` {url}")

        # Syllabus
        if course["syllabus_body"]:
            lines.append("")
            lines.append("## Syllabus (HTML)")
            lines.append("")
            lines.append("(raw HTML copied from Canvas)")
            lines.append("")
            lines.append("```html")
            lines.append(str(course["syllabus_body"]))
            lines.append("```")

        path.write_text("\n".join(lines) + "\n")

    console.print(f"Wrote Markdown course files to: {out}")
    return 0
