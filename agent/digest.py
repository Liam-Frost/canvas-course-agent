from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from rich.console import Console

from .discord_webhook import discord_send
from .storage.sqlite import connect, list_courses, list_starred_course_ids
from .timeutil import fmt_canvas_dt_2line, get_tz, parse_canvas_dt, tz_label

console = Console()


@dataclass
class DigestItem:
    kind: str  # assignment|quiz|custom
    course: str
    title: str
    start_at: str
    due_at: str
    url: str


def _course_name_map(conn) -> dict[int, str]:
    rows = list_courses(conn)
    return {int(r["id"]): str(r["name"] or r["course_code"] or r["id"]) for r in rows}


def build_digest(*, db_path: str, days: int, all_courses: bool, timezone: str) -> list[DigestItem]:
    conn = connect(db_path)
    tz = get_tz(timezone)

    course_name_by_id = _course_name_map(conn)
    course_ids = [int(r["id"]) for r in list_courses(conn)] if all_courses else list_starred_course_ids(conn)

    now = datetime.now(UTC)
    end = now + timedelta(days=days)

    items: list[DigestItem] = []

    # Dedupe set for quizzes-as-assignments
    quiz_rows = conn.execute(
        "SELECT course_id, raw_json FROM quizzes WHERE course_id IN (%s)" % ",".join("?" * len(course_ids)),
        course_ids,
    ).fetchall() if course_ids else []

    assignment_ids_from_quizzes: set[int] = set()

    for r in quiz_rows:
        raw = json.loads(r["raw_json"])
        if raw.get("quiz_type") == "assignment" and raw.get("assignment_id"):
            try:
                assignment_ids_from_quizzes.add(int(raw["assignment_id"]))
            except Exception:
                pass

        ref = raw.get("unlock_at") or raw.get("due_at")
        dt = parse_canvas_dt(ref)
        if not dt or not (now <= dt <= end):
            continue

        cid = int(r["course_id"])
        items.append(
            DigestItem(
                kind="quiz",
                course=course_name_by_id.get(cid, str(cid)),
                title=str(raw.get("title") or ""),
                start_at=str(raw.get("unlock_at") or ""),
                due_at=str(raw.get("due_at") or ""),
                url=str(raw.get("html_url") or ""),
            )
        )

    # Assignments
    asg_rows = conn.execute(
        "SELECT id, course_id, name, due_at, unlock_at, html_url FROM assignments WHERE course_id IN (%s)" % ",".join("?" * len(course_ids)),
        course_ids,
    ).fetchall() if course_ids else []

    for r in asg_rows:
        asg_id = int(r["id"])
        if asg_id in assignment_ids_from_quizzes:
            continue

        dt = parse_canvas_dt(r["due_at"])
        if not dt or not (now <= dt <= end):
            continue

        cid = int(r["course_id"])
        items.append(
            DigestItem(
                kind="assignment",
                course=course_name_by_id.get(cid, str(cid)),
                title=str(r["name"] or ""),
                start_at=str(r["unlock_at"] or ""),
                due_at=str(r["due_at"] or ""),
                url=str(r["html_url"] or ""),
            )
        )

    # Custom reminders
    custom_rows = conn.execute(
        "SELECT title, at_utc, channels, silent, enabled FROM custom_reminders WHERE enabled=1"
    ).fetchall()

    for r in custom_rows:
        at_utc = datetime.fromisoformat(r["at_utc"])
        if not (now <= at_utc <= end):
            continue
        items.append(
            DigestItem(
                kind="custom",
                course="(custom)",
                title=str(r["title"]),
                start_at=at_utc.replace(microsecond=0).isoformat(),
                due_at=at_utc.replace(microsecond=0).isoformat(),
                url="",
            )
        )

    def sort_key(it: DigestItem) -> datetime:
        return parse_canvas_dt(it.start_at) or parse_canvas_dt(it.due_at) or datetime.max.replace(tzinfo=UTC)

    items.sort(key=sort_key)
    return items


def format_digest(*, items: list[DigestItem], days: int, timezone: str) -> str:
    tz = get_tz(timezone)
    tzs = tz_label(tz)

    if not items:
        return f"No upcoming items in next {days} days. ({tzs})"

    # Group by local date for readability
    grouped: dict[str, list[DigestItem]] = {}
    for it in items:
        dt = parse_canvas_dt(it.start_at or it.due_at)
        if not dt:
            key = "(unknown date)"
        else:
            key = dt.astimezone(tz).date().isoformat()
        grouped.setdefault(key, []).append(it)

    dates = sorted(grouped.keys())

    lines: list[str] = []
    lines.append(f"**Upcoming {days} days** ({tzs})")

    for d in dates:
        lines.append("")
        lines.append(f"**{d}**")
        for it in grouped[d]:
            dt = parse_canvas_dt(it.start_at or it.due_at)
            time_str = ""
            if dt:
                local = dt.astimezone(tz).replace(microsecond=0)
                time_str = local.strftime("%H:%M") + " " + (local.tzname() or "")
            kind = it.kind
            # concise, scannable bullet
            bullet = f"- [{kind}] {it.course}: {it.title}"
            if time_str:
                bullet += f" — {time_str}"
            lines.append(bullet)
            if it.url:
                lines.append(f"  {it.url}")

    return "\n".join(lines)


def _split_for_discord(text: str, limit: int = 1800) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    n = 0
    for line in text.splitlines():
        add = len(line) + 1
        if n + add > limit and buf:
            parts.append("\n".join(buf))
            buf = []
            n = 0
        buf.append(line)
        n += add
    if buf:
        parts.append("\n".join(buf))
    return parts


def cmd_digest(
    *,
    db_path: str,
    days: int,
    all_courses: bool,
    timezone: str,
    discord_webhook_url: str | None,
    send_discord: bool,
) -> int:
    items = build_digest(db_path=db_path, days=days, all_courses=all_courses, timezone=timezone)
    msg = format_digest(items=items, days=days, timezone=timezone)

    console.print(msg)

    if send_discord:
        if not discord_webhook_url:
            raise SystemExit("DISCORD_WEBHOOK_URL is not set")
        chunks = _split_for_discord(msg)
        for c in chunks:
            discord_send(webhook_url=discord_webhook_url, content=c)
        console.print(f"Sent digest to Discord. (messages={len(chunks)})")

    return 0
