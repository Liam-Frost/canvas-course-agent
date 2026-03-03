from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.table import Table

from .storage.sqlite import connect
from .timeutil import get_tz, tz_label

console = Console()


def _parse_in(s: str) -> timedelta:
    s = s.strip().lower()
    if s.endswith("m"):
        return timedelta(minutes=int(s[:-1]))
    if s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    raise SystemExit("--in supports suffix m or h, e.g. 90m or 2h")


def _parse_at_local(s: str, tz) -> datetime:
    # Accept "YYYY-MM-DD HH:MM" (no seconds)
    s = s.strip()
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
    except Exception:
        raise SystemExit("--at format: YYYY-MM-DD HH:MM (e.g. 2026-03-05 13:00)")
    return dt.replace(tzinfo=tz)


def cmd_remind_add(
    *,
    db_path: str,
    timezone: str,
    title: str,
    at: str | None,
    in_: str | None,
    channels: str,
    silent: bool,
) -> int:
    tz = get_tz(timezone)
    now = datetime.now(UTC)

    if bool(at) == bool(in_):
        raise SystemExit("Provide exactly one of --at or --in")

    if at:
        local_dt = _parse_at_local(at, tz)
        at_utc = local_dt.astimezone(UTC)
    else:
        at_utc = now + _parse_in(in_ or "")

    ch = [c.strip().lower() for c in channels.split(",") if c.strip()]
    if not ch:
        raise SystemExit("--channels must include discord and/or telegram")
    for c in ch:
        if c not in {"discord", "telegram"}:
            raise SystemExit("--channels must be discord, telegram, or discord,telegram")

    conn = connect(db_path)
    with conn:
        conn.execute(
            "INSERT INTO custom_reminders (title, at_utc, channels, silent) VALUES (?, ?, ?, ?)",
            (title, at_utc.replace(microsecond=0).isoformat(), ",".join(ch), 1 if silent else 0),
        )

    console.print(f"Added custom reminder at {at_utc.isoformat()} UTC: {title}")
    return 0


def cmd_remind_list(*, db_path: str, timezone: str) -> int:
    tz = get_tz(timezone)
    tzs = tz_label(tz)
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT id, title, at_utc, channels, silent, enabled FROM custom_reminders ORDER BY at_utc"
    ).fetchall()

    t = Table(title=f"Custom reminders ({len(rows)})")
    t.add_column("id", justify="right")
    t.add_column("enabled")
    t.add_column("channels")
    t.add_column("silent")
    t.add_column(f"at({tzs})")
    t.add_column("title")

    for r in rows:
        dt = datetime.fromisoformat(r["at_utc"])
        local = dt.astimezone(tz)
        t.add_row(
            str(r["id"]),
            "yes" if r["enabled"] else "no",
            str(r["channels"]),
            "yes" if r["silent"] else "",
            f"{local.date().isoformat()}\n{local.strftime('%H:%M')} {local.tzname() or ''}".rstrip(),
            str(r["title"]),
        )

    console.print(t)
    return 0


def cmd_remind_disable(*, db_path: str, reminder_id: int) -> int:
    conn = connect(db_path)
    with conn:
        cur = conn.execute("UPDATE custom_reminders SET enabled=0 WHERE id=?", (reminder_id,))
    if cur.rowcount == 0:
        raise SystemExit(f"No such reminder id: {reminder_id}")
    console.print(f"Disabled reminder {reminder_id}")
    return 0
