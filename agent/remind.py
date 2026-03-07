from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from rich.console import Console
from rich.table import Table

from .discord_webhook import discord_send
from .course_label import format_course_label
from .storage.sqlite import connect, get_setting
from .telegram_cmd import telegram_send
from .timeutil import fmt_canvas_dt_2line, get_tz, parse_canvas_dt, tz_label

console = Console()


@dataclass
class Reminder:
    channel: str  # discord|telegram
    silent: bool
    kind: str  # assignment|quiz|custom
    item_id: int
    course_name: str
    title: str
    when: datetime  # trigger time (UTC)
    ref_time: datetime  # due/unlock/at time (UTC)
    url: str


def _course_name_map(conn, *, short_enabled: bool) -> dict[int, str]:
    rows = conn.execute("SELECT id, name, course_code FROM courses").fetchall()
    out: dict[int, str] = {}
    for r in rows:
        out[int(r[0])] = format_course_label(
            str(r[1] or ""),
            r[2],
            short_enabled=short_enabled,
        ) or str(r[0])
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


def _topic_for_item(conn, *, kind: str, item_id: int) -> tuple[str | None, float | None]:
    r = conn.execute(
        "SELECT primary_topic, confidence FROM ai_task_mapping_resolved WHERE kind=? AND item_id=?",
        (kind, item_id),
    ).fetchone()
    if not r:
        return None, None
    topic = str(r[0]) if r[0] else None
    conf = float(r[1]) if r[1] is not None else None
    return topic, conf


def _eta_for_item(conn, *, kind: str, item_id: int) -> int | None:
    if kind == "assignment":
        r = conn.execute("SELECT raw_json FROM assignments WHERE id=?", (item_id,)).fetchone()
        if not r:
            return None
        try:
            raw = json.loads(r[0] or "{}")
        except Exception:
            return None
        pts = raw.get("points_possible")
        if pts is None:
            return None
        try:
            return int(max(20, min(300, float(pts) * 6)))
        except Exception:
            return None

    if kind == "quiz":
        r = conn.execute("SELECT raw_json FROM quizzes WHERE id=?", (item_id,)).fetchone()
        if not r:
            return None
        try:
            raw = json.loads(r[0] or "{}")
        except Exception:
            return None
        tl = raw.get("time_limit")
        if tl is None:
            return None
        try:
            return int(max(10, min(180, int(tl) + 20)))
        except Exception:
            return None

    return None


def _format_reminder_message(conn, *, rm: Reminder, timezone: str) -> str:
    tz = get_tz(timezone)
    ref = rm.ref_time.astimezone(tz).strftime("%m-%d %a %H:%M")
    tzs = tz_label(tz)

    icon = "📝" if rm.kind == "assignment" else ("🧪" if rm.kind == "quiz" else "⏰")
    kind_label = "Assignment" if rm.kind == "assignment" else ("Quiz" if rm.kind == "quiz" else "Reminder")

    topic, conf = _topic_for_item(conn, kind=rm.kind, item_id=rm.item_id)
    eta = _eta_for_item(conn, kind=rm.kind, item_id=rm.item_id)

    lines: list[str] = []
    lines.append(f"{icon} **[{rm.course_name}]** {rm.title}")
    lines.append(f"📌 类型：{kind_label}")
    if topic:
        if conf is not None and conf < 0.6:
            lines.append(f"🧠 主题：可能是 {topic} (低置信)")
        else:
            lines.append(f"🧠 主题：{topic}")
    if eta is not None:
        lines.append(f"⏱ 预计用时：~{eta} 分钟")
    lines.append(f"🕒 截止：{ref} {tzs}")
    if rm.url:
        lines.append("🔗 [打开任务](" + rm.url + ")")

    return "\n".join(lines)


def _candidate_reminders(
    *,
    conn,
    lookahead_min: int,
    timezone: str,
    short_course_label: bool,
) -> Iterable[Reminder]:
    now = datetime.now(UTC)
    look_end = now + timedelta(minutes=lookahead_min)

    tz = get_tz(timezone)
    _ = tz_label(tz)

    course_name_by_id = _course_name_map(conn, short_enabled=short_course_label)
    course_ids = _iter_starred_course_ids(conn)
    if not course_ids:
        return []

    # Settings (minutes)
    asg_offsets = _parse_offsets(get_setting(conn, "remind.assignment.offsets", "60"), [60])
    quiz_loud = _parse_offsets(get_setting(conn, "remind.quiz.offsets_loud", "60"), [60])
    quiz_silent = _parse_offsets(get_setting(conn, "remind.quiz.offsets_silent", "10"), [10])

    discord_enabled = (get_setting(conn, "remind.discord.enabled", "on") or "on") == "on"
    telegram_enabled = (get_setting(conn, "remind.telegram.enabled", "on") or "on") == "on"

    # Quizzes: use unlock_at as primary reference
    quiz_rows = conn.execute(
        "SELECT id, course_id, title, raw_json FROM quizzes WHERE course_id IN (%s)" % ",".join("?" * len(course_ids)),
        course_ids,
    ).fetchall()

    quiz_assignment_ids: set[int] = set()

    for r in quiz_rows:
        raw: dict[str, Any] = json.loads(r[3])
        if raw.get("quiz_type") == "assignment" and raw.get("assignment_id"):
            try:
                quiz_assignment_ids.add(int(raw.get("assignment_id")))
            except Exception:
                pass

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
                if ch == "discord" and not discord_enabled:
                    continue
                if ch == "telegram" and not telegram_enabled:
                    continue
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
            if not telegram_enabled:
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

    # Custom reminders
    custom_rows = conn.execute(
        "SELECT id, title, at_utc, channels, silent FROM custom_reminders WHERE enabled=1"
    ).fetchall()

    for r in custom_rows:
        at_utc = datetime.fromisoformat(r["at_utc"])
        if not (now <= at_utc <= look_end):
            continue
        channels = {c.strip().lower() for c in str(r["channels"] or "").split(",") if c.strip()}
        silent = bool(r["silent"])

        if "discord" in channels and discord_enabled:
            yield Reminder(
                channel="discord",
                silent=False,
                kind="custom",
                item_id=int(r["id"]),
                course_name="(custom)",
                title=str(r["title"]),
                when=at_utc,
                ref_time=at_utc,
                url="",
            )
        if "telegram" in channels and telegram_enabled:
            yield Reminder(
                channel="telegram",
                silent=silent,
                kind="custom",
                item_id=int(r["id"]),
                course_name="(custom)",
                title=str(r["title"]),
                when=at_utc,
                ref_time=at_utc,
                url="",
            )

    # Assignments: use due_at (but skip those that are represented by quizzes)
    asg_rows = conn.execute(
        "SELECT id, course_id, name, due_at, html_url, raw_json FROM assignments WHERE course_id IN (%s)"
        % ",".join("?" * len(course_ids)),
        course_ids,
    ).fetchall()

    for r in asg_rows:
        asg_id = int(r[0])
        if asg_id in quiz_assignment_ids:
            continue

        due = parse_canvas_dt(r[3])
        if not due:
            continue
        for off in asg_offsets:
            when = due - timedelta(minutes=off)
            if not (now <= when <= look_end):
                continue
            if discord_enabled:
                yield Reminder(
                    channel="discord",
                    silent=False,
                    kind="assignment",
                    item_id=asg_id,
                    course_name=course_name_by_id.get(int(r[1]), str(r[1])),
                    title=str(r[2] or ""),
                    when=when,
                    ref_time=due,
                    url=str(r[4] or ""),
                )

            if telegram_enabled:
                yield Reminder(
                    channel="telegram",
                    silent=False,
                    kind="assignment",
                    item_id=asg_id,
                    course_name=course_name_by_id.get(int(r[1]), str(r[1])),
                    title=str(r[2] or ""),
                    when=when,
                    ref_time=due,
                    url=str(r[4] or ""),
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
    course_label_short: bool = False,
) -> int:
    conn = connect(db_path)

    remind_enabled = (get_setting(conn, "remind.enabled", "on") or "on") == "on"
    if not remind_enabled:
        console.print("Reminders are globally disabled (remind.enabled=off).")
        return 0

    tz = get_tz(timezone)
    tzs = tz_label(tz)

    reminders = list(
        _candidate_reminders(
            conn=conn,
            lookahead_min=lookahead_min,
            timezone=timezone,
            short_course_label=course_label_short,
        )
    )

    t = Table(title=f"Reminders (lookahead {lookahead_min} min)")
    t.add_column("when\n(UTC)")
    t.add_column("channel")
    t.add_column("silent")
    t.add_column("type")
    t.add_column("course")
    t.add_column("title")
    t.add_column(f"ref_time\n({tzs})")

    for rm in sorted(reminders, key=lambda r: r.when):
        t.add_row(
            rm.when.replace(microsecond=0).strftime("%Y-%m-%d\n%H:%MZ"),
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

            # Build B+ reminder card message
            msg = _format_reminder_message(conn, rm=rm, timezone=timezone)

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
