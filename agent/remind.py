from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from rich.console import Console
from rich.table import Table

from .discord_webhook import discord_send
from .storage.sqlite import connect, get_setting
from .telegram_cmd import telegram_send
from .timeutil import fmt_canvas_dt_2line, get_tz, parse_canvas_dt, tz_label

console = Console()


@dataclass
class Reminder:
    channel: str  # discord|telegram
    silent: bool
    kind: str  # assignment|quiz
    item_id: int
    course_name: str
    title: str
    when: datetime  # trigger time (UTC)
    ref_time: datetime  # due/unlock time (UTC)
    url: str


def _course_name_map(conn) -> dict[int, str]:
    rows = conn.execute("SELECT id, name, course_code FROM courses").fetchall()
    out: dict[int, str] = {}
    for r in rows:
        out[int(r[0])] = str(r[1] or r[2] or r[0])
    return out


def _parse_offsets(value: str | None, default: list[int]) -> list[int]:
    if not value:
        return default
    parts = [p.strip() for p in value.split(",")]
    out: list[int] = []
    for p in parts:
        if not p:
            continue
        out.append(int(p))
    return out


def _already_sent(conn, *, kind: str, item_id: int, channel: str, remind_at: datetime) -> bool:
    r = conn.execute(
        "SELECT 1 FROM notifications_sent WHERE kind=? AND item_id=? AND channel=? AND remind_at=?",
        (kind, item_id, channel, remind_at.replace(microsecond=0).isoformat()),
    ).fetchone()
    return r is not None


def _mark_sent(conn, *, kind: str, item_id: int, channel: str, remind_at: datetime) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO notifications_sent (kind, item_id, channel, remind_at) VALUES (?, ?, ?, ?)",
        (kind, item_id, channel, remind_at.replace(microsecond=0).isoformat()),
    )


def _iter_starred_course_ids(conn) -> list[int]:
    return [int(r[0]) for r in conn.execute("SELECT course_id FROM starred_courses").fetchall()]


def _candidate_reminders(
    *,
    conn,
    lookahead_min: int,
    timezone: str,
) -> Iterable[Reminder]:
    now = datetime.now(UTC)
    look_end = now + timedelta(minutes=lookahead_min)

    tz = get_tz(timezone)
    _ = tz_label(tz)

    course_name_by_id = _course_name_map(conn)
    course_ids = _iter_starred_course_ids(conn)
    if not course_ids:
        return []

    # Settings (minutes)
    asg_offsets = _parse_offsets(get_setting(conn, "remind.assignment.offsets", "60"), [60])
    quiz_loud = _parse_offsets(get_setting(conn, "remind.quiz.offsets_loud", "60"), [60])
    quiz_silent = _parse_offsets(get_setting(conn, "remind.quiz.offsets_silent", "10"), [10])

    # Assignments: use due_at
    asg_rows = conn.execute(
        "SELECT id, course_id, name, due_at, html_url, raw_json FROM assignments WHERE course_id IN (%s)"
        % ",".join("?" * len(course_ids)),
        course_ids,
    ).fetchall()

    for r in asg_rows:
        due = parse_canvas_dt(r[3])
        if not due:
            continue
        for off in asg_offsets:
            when = due - timedelta(minutes=off)
            if not (now <= when <= look_end):
                continue
            yield Reminder(
                channel="discord",
                silent=False,
                kind="assignment",
                item_id=int(r[0]),
                course_name=course_name_by_id.get(int(r[1]), str(r[1])),
                title=str(r[2] or ""),
                when=when,
                ref_time=due,
                url=str(r[4] or ""),
            )
            yield Reminder(
                channel="telegram",
                silent=False,
                kind="assignment",
                item_id=int(r[0]),
                course_name=course_name_by_id.get(int(r[1]), str(r[1])),
                title=str(r[2] or ""),
                when=when,
                ref_time=due,
                url=str(r[4] or ""),
            )

    # Quizzes: use unlock_at as primary reference
    quiz_rows = conn.execute(
        "SELECT id, course_id, title, raw_json FROM quizzes WHERE course_id IN (%s)" % ",".join("?" * len(course_ids)),
        course_ids,
    ).fetchall()

    for r in quiz_rows:
        raw: dict[str, Any] = json.loads(r[3])
        unlock = parse_canvas_dt(raw.get("unlock_at"))
        due = parse_canvas_dt(raw.get("due_at"))
        ref = unlock or due
        if not ref:
            continue

        for off in quiz_loud:
            when = ref - timedelta(minutes=off)
            if not (now <= when <= look_end):
                continue
            for ch in ("discord", "telegram"):
                yield Reminder(
                    channel=ch,
                    silent=False,
                    kind="quiz",
                    item_id=int(r[0]),
                    course_name=course_name_by_id.get(int(r[1]), str(r[1])),
                    title=str(r[2] or ""),
                    when=when,
                    ref_time=ref,
                    url=str(raw.get("html_url") or ""),
                )

        for off in quiz_silent:
            when = ref - timedelta(minutes=off)
            if not (now <= when <= look_end):
                continue
            yield Reminder(
                channel="telegram",
                silent=True,
                kind="quiz",
                item_id=int(r[0]),
                course_name=course_name_by_id.get(int(r[1]), str(r[1])),
                title=str(r[2] or ""),
                when=when,
                ref_time=ref,
                url=str(raw.get("html_url") or ""),
            )


def remind_run(
    *,
    db_path: str,
    timezone: str,
    lookahead_min: int = 2,
    send_discord: bool = False,
    send_telegram: bool = False,
    dry_run: bool = True,
    discord_webhook_url: str | None = None,
    telegram_bot_token: str | None = None,
) -> int:
    conn = connect(db_path)

    tz = get_tz(timezone)
    tzs = tz_label(tz)


    reminders = list(_candidate_reminders(conn=conn, lookahead_min=lookahead_min, timezone=timezone))

    t = Table(title=f"Reminders (lookahead {lookahead_min} min)")
    t.add_column("when(UTC)")
    t.add_column("channel")
    t.add_column("silent")
    t.add_column("type")
    t.add_column("course")
    t.add_column("title")
    t.add_column(f"ref_time({tzs})")

    for rm in sorted(reminders, key=lambda r: r.when):
        t.add_row(
            rm.when.replace(microsecond=0).isoformat(),
            rm.channel,
            "yes" if rm.silent else "",
            rm.kind,
            rm.course_name,
            rm.title,
            fmt_canvas_dt_2line(rm.ref_time.isoformat(), tz),
        )
    console.print(t)

    if dry_run:
        return 0

    telegram_chat_id = None
    if send_telegram:
        telegram_chat_id = get_setting(conn, "telegram.chat_id")
        if not telegram_chat_id:
            raise SystemExit("telegram.chat_id not set. Run: canvas-agent telegram link")
        if not telegram_bot_token:
            raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    if send_discord and not discord_webhook_url:
        raise SystemExit("DISCORD_WEBHOOK_URL is not set")

    sent = 0
    with conn:
        for rm in sorted(reminders, key=lambda r: r.when):
            if rm.channel == "discord" and not send_discord:
                continue
            if rm.channel == "telegram" and not send_telegram:
                continue

            if _already_sent(conn, kind=rm.kind, item_id=rm.item_id, channel=rm.channel, remind_at=rm.when):
                continue

            # Build message
            local_ref = fmt_canvas_dt_2line(rm.ref_time.isoformat(), tz)
            msg = f"[{rm.kind}] {rm.course_name}: {rm.title}\nTime: {local_ref}"
            if rm.url:
                msg += f"\n{rm.url}"

            if rm.channel == "discord":
                discord_send(webhook_url=discord_webhook_url or "", content=msg)
            else:
                telegram_send(
                    bot_token=telegram_bot_token or "",
                    chat_id=str(telegram_chat_id),
                    text=msg,
                    silent=rm.silent,
                )

            _mark_sent(conn, kind=rm.kind, item_id=rm.item_id, channel=rm.channel, remind_at=rm.when)
            sent += 1

    console.print(f"Sent {sent} reminder(s).")
    return 0
