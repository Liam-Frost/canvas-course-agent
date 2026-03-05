from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from rich.console import Console

from .ai_adapter import AIAdapter, AIAdapterError
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
    end_at: str
    due_at: str
    url: str
    course_id: int | None = None
    item_id: int | None = None
    ai_note: str | None = None


def _short_course_label(name: str, code: str | None) -> str:
    """Try to derive a compact label like 'CPEN 212' from Canvas course_code/name."""
    text = f"{code or ''} {name}".strip()
    # Common UBC patterns: CPEN_V 212 ..., CPSC_V 221 ..., MATH_V 256 ...
    import re

    m = re.search(r"\b([A-Z]{3,5})[_\s-]*[A-Z]?\s*(\d{3})\b", text)
    if m:
        return f"{m.group(1)} {m.group(2)}"

    # fallback: course_code if it exists, else name
    return (code or name).strip()


def _course_name_map(conn) -> dict[int, str]:
    rows = list_courses(conn)
    out: dict[int, str] = {}
    for r in rows:
        out[int(r["id"])] = _short_course_label(str(r["name"] or ""), r["course_code"])
    return out


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
        # Quiz window: start=unlock_at (or due_at fallback). end prefers lock_at, else start+time_limit, else due.
        start_s = str(raw.get("unlock_at") or raw.get("due_at") or "")
        lock_s = str(raw.get("lock_at") or "")
        end_s = lock_s
        if not end_s:
            start_dt = parse_canvas_dt(start_s)
            tl = raw.get("time_limit")
            if start_dt and tl is not None:
                try:
                    end_s = (start_dt + timedelta(minutes=int(tl))).isoformat()
                except Exception:
                    end_s = ""
        if not end_s:
            end_s = str(raw.get("due_at") or "")

        items.append(
            DigestItem(
                kind="quiz",
                course=course_name_by_id.get(cid, str(cid)),
                title=str(raw.get("title") or ""),
                start_at=start_s,
                end_at=end_s,
                due_at=str(raw.get("due_at") or ""),
                url=str(raw.get("html_url") or ""),
                course_id=cid,
                item_id=int(raw.get("id")) if raw.get("id") is not None else None,
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
        due_s = str(r["due_at"] or "")
        items.append(
            DigestItem(
                kind="assignment",
                course=course_name_by_id.get(cid, str(cid)),
                title=str(r["name"] or ""),
                # For digest purposes, assignments should be keyed/sorted by due time.
                start_at=due_s,
                end_at="",
                due_at=due_s,
                url=str(r["html_url"] or ""),
                course_id=cid,
                item_id=asg_id,
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
                end_at="",
                due_at=at_utc.replace(microsecond=0).isoformat(),
                url="",
            )
        )

    def sort_key(it: DigestItem) -> datetime:
        return parse_canvas_dt(it.start_at) or parse_canvas_dt(it.due_at) or datetime.max.replace(tzinfo=UTC)

    items.sort(key=sort_key)
    return items


def annotate_digest_items_ai(
    *,
    conn,
    items: list[DigestItem],
    adapter: AIAdapter,
) -> None:
    for it in items:
        if it.kind not in ("assignment", "quiz"):
            continue

        ann_titles: list[str] = []
        if it.course_id is not None:
            rows = conn.execute(
                "SELECT title FROM course_announcements WHERE course_id=? ORDER BY COALESCE(posted_at, delayed_post_at) DESC LIMIT 2",
                (it.course_id,),
            ).fetchall()
            ann_titles = [str(r["title"] or "") for r in rows if (r["title"] or "").strip()]

        prompt = "\n".join(
            [
                "Write ONE short Chinese description (<=30 chars) for this Canvas task.",
                "Must be concrete and action-oriented. No markdown, no prefix, one line only.",
                f"Course: {it.course}",
                f"Type: {it.kind}",
                f"Task: {it.title}",
                f"Due/Start: {it.due_at or it.start_at}",
                "Recent announcements:",
                *([f"- {t}" for t in ann_titles] or ["- (none)"]),
            ]
        )

        try:
            text = adapter.complete(prompt).strip()
            # keep only first line and clamp
            text = text.splitlines()[0].strip()
            if len(text) > 60:
                text = text[:60].rstrip() + "…"
            it.ai_note = text
        except AIAdapterError:
            it.ai_note = None


def _item_ref_dt(it: DigestItem):
    if it.kind == "quiz":
        return parse_canvas_dt(it.start_at) or parse_canvas_dt(it.due_at)
    return parse_canvas_dt(it.due_at) or parse_canvas_dt(it.start_at)


def format_weekly_digest_v2(
    *,
    items: list[DigestItem],
    timezone: str,
    now_utc: datetime | None = None,
    action_plan: list[str] | None = None,
) -> str:
    tz = get_tz(timezone)
    tzs = tz_label(tz)
    now = now_utc or datetime.now(UTC)
    h48 = now + timedelta(hours=48)
    h7d = now + timedelta(days=7)
    h14d = now + timedelta(days=14)

    urgent: list[DigestItem] = []
    this_week: list[DigestItem] = []
    next_week: list[DigestItem] = []

    for it in items:
        dt = _item_ref_dt(it)
        if not dt:
            continue
        if now <= dt <= h48:
            urgent.append(it)
        elif h48 < dt <= h7d:
            this_week.append(it)
        elif h7d < dt <= h14d:
            next_week.append(it)

    def _render_block(title: str, block: list[DigestItem]) -> list[str]:
        lines: list[str] = [f"**{title}**"]
        if not block:
            lines.append("- (none)")
            lines.append("")
            return lines

        for it in sorted(block, key=lambda x: _item_ref_dt(x) or datetime.max.replace(tzinfo=UTC)):
            dt = _item_ref_dt(it)
            local = dt.astimezone(tz).strftime("%m-%d %a %H:%M") if dt else "(unknown)"
            icon = "🧪" if it.kind == "quiz" else ("📝" if it.kind == "assignment" else "⏰")
            lines.append(f"- {icon} **[{it.course}]** {it.title} · `{local} {tzs}`")
            if it.ai_note:
                lines.append(f"  - {it.ai_note}")
            if it.url:
                lines.append(f"  - [Open]({it.url})")
        lines.append("")
        return lines

    total = len(items)
    high = len(urgent)

    out: list[str] = []
    out.append(f"**Weekly Digest v2** ({tzs})")
    out.append(f"- 总任务: **{total}** | 48h高优先级: **{high}**")
    out.append("")
    out += _render_block("🔥 48h 内", urgent)
    out += _render_block("📌 本周其余", this_week)
    out += _render_block("🧊 下周预告", next_week)

    out.append("**✅ 本周行动清单**")
    if action_plan:
        for a in action_plan[:5]:
            out.append(f"- [ ] {a}")
    else:
        # fallback checklist from urgent tasks
        if urgent:
            for it in urgent[:5]:
                out.append(f"- [ ] 优先完成 {it.course} / {it.title}")
        else:
            out.append("- [ ] 清空本周低优先级待办")

    return "\n".join(out)


def format_digest(*, items: list[DigestItem], days: int, timezone: str) -> str:
    tz = get_tz(timezone)
    tzs = tz_label(tz)

    if not items:
        return f"No upcoming items in next {days} days. ({tzs})"

    # Group by local date for readability
    grouped: dict[str, list[DigestItem]] = {}
    def _ref_dt(it: DigestItem):
        # Quizzes are keyed by start (unlock). Assignments/custom are keyed by due/at.
        if it.kind == "quiz":
            return parse_canvas_dt(it.start_at) or parse_canvas_dt(it.due_at)
        return parse_canvas_dt(it.due_at) or parse_canvas_dt(it.start_at)

    for it in items:
        dt = _ref_dt(it)
        if not dt:
            key = "(unknown date)"
        else:
            key = dt.astimezone(tz).date().isoformat()
        grouped.setdefault(key, []).append(it)

    dates = sorted(grouped.keys())

    def heading(date_iso: str) -> str:
        if date_iso == "(unknown date)":
            return date_iso

        # date_iso is already a *local date key* (we grouped by dt.astimezone(tz).date()).
        # So compute DOW in the same timezone; do NOT treat it as UTC midnight,
        # otherwise timezones west of UTC will shift to the previous day.
        y, m, d = (int(x) for x in date_iso.split("-"))
        dt = datetime(y, m, d, 0, 0, 0, tzinfo=tz)
        dow = dt.strftime("%a")  # Mon/Tue

        if days >= 28:
            # week-of-month (1-5)
            wom = (dt.day - 1) // 7 + 1
            return f"{date_iso}  |  Week {wom}  |  {dow}"
        return f"{date_iso} ({dow})"

    lines: list[str] = []
    lines.append(f"**Upcoming {days} days** ({tzs})")

    icon = {"quiz": "🧪 Quiz", "assignment": "📝 Asg", "custom": "⏰ Custom"}

    for d in dates:
        lines.append("")
        lines.append(f"**{heading(d)}**")

        day_items = grouped[d]
        for idx, it in enumerate(day_items):
            kind_label = icon.get(it.kind, f"[{it.kind}]")

            # Multi-line, field-first layout:
            # - Time: 14:00–14:11 PDT
            # - Course: CPEN 212
            # - Task: Quiz — Concurrency I
            start_dt = parse_canvas_dt(it.start_at) or parse_canvas_dt(it.due_at)
            end_dt = parse_canvas_dt(it.end_at)
            due_dt = parse_canvas_dt(it.due_at)

            def _t(dt):
                if not dt:
                    return ""
                loc = dt.astimezone(tz).replace(microsecond=0)
                return loc.strftime("%H:%M")

            tzabbr = (
                start_dt.astimezone(tz).tzname()
                if start_dt
                else datetime.now(UTC).astimezone(tz).tzname()
            ) or tzs

            # Quiz: show start–end (preferred); fallback to due.
            if it.kind == "quiz" and start_dt:
                if end_dt:
                    time_line = f"**{_t(start_dt)}–{_t(end_dt)} {tzabbr}**"
                else:
                    time_line = f"**{_t(start_dt)} {tzabbr}**"
            else:
                # assignment/custom: show due time
                ref = due_dt or start_dt
                time_line = f"**{_t(ref)} {tzabbr}**" if ref else ""

            # Requested layout:
            # 1) type
            # 2) course
            # 3) task name
            # 4) bold time
            # 5) short link text
            # Quote block per task for visual separation in Discord.
            # A blank line ends the quote, so we can render each task as its own block.
            lines.append(f"> {kind_label}")
            lines.append(f"> Course: **{it.course}**")
            lines.append(f"> Task: {it.title}")
            if it.ai_note:
                lines.append(f"> Note: {it.ai_note}")
            if time_line:
                lines.append(f"> Time: {time_line}")
            if it.url:
                lines.append(f"> Link: [Open]({it.url})")

            if idx != len(day_items) - 1:
                lines.append("")
    return "\n".join(lines)


def build_action_plan_ai(*, adapter: AIAdapter, items: list[DigestItem], timezone: str) -> list[str]:
    top = []
    for it in items[:10]:
        dt = _item_ref_dt(it)
        top.append(f"- {it.course} | {it.kind} | {it.title} | {dt.isoformat() if dt else ''}")

    prompt = "\n".join(
        [
            "给我一个本周学习行动清单，最多5条，每条一句中文，不要序号。",
            "优先考虑48小时内截止和高压力任务。",
            f"Timezone: {timezone}",
            "Tasks:",
            *top,
        ]
    )

    try:
        out = adapter.complete(prompt)
    except AIAdapterError:
        return []

    lines = [ln.strip("- •\t ") for ln in out.splitlines() if ln.strip()]
    clean = [ln for ln in lines if ln]
    return clean[:5]


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
    ai_describe: bool = False,
    ai_provider: str = "auto",
    ai_model: str | None = None,
    openai_api_key: str | None = None,
    openai_base_url: str = "https://api.openai.com/v1",
    weekly_v2: bool = False,
    ai_weekly_plan: bool = False,
) -> int:
    conn = connect(db_path)
    items = build_digest(db_path=db_path, days=days, all_courses=all_courses, timezone=timezone)

    adapter: AIAdapter | None = None
    if (ai_describe or ai_weekly_plan) and items:
        adapter = AIAdapter(
            provider=ai_provider,
            model=ai_model,
            openai_api_key=openai_api_key,
            openai_base_url=openai_base_url,
        )

    if ai_describe and items and adapter is not None:
        annotate_digest_items_ai(conn=conn, items=items, adapter=adapter)

    if weekly_v2:
        plan = build_action_plan_ai(adapter=adapter, items=items, timezone=timezone) if (ai_weekly_plan and adapter is not None) else None
        msg = format_weekly_digest_v2(items=items, timezone=timezone, action_plan=plan)
    else:
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
