from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .ai_adapter import AIAdapter, AIAdapterError

from .providers.canvas import CanvasClient
from .storage.sqlite import (
    connect,
    list_courses,
    list_starred_course_ids,
    replace_course_announcements,
    replace_course_discussions,
    replace_course_files,
    replace_course_modules,
    replace_course_pages,
    replace_course_people,
    upsert_assignment,
    upsert_assignment_submission,
    upsert_course,
    upsert_quiz,
)
from .timeutil import parse_canvas_dt

console = Console()


def _selected_course_ids(conn, *, all_courses: bool) -> list[int]:
    rows = list_courses(conn)
    if all_courses:
        return [int(r["id"]) for r in rows]
    return list_starred_course_ids(conn)


def sync_profiles(
    client: CanvasClient,
    *,
    db_path: str,
    all_courses: bool = False,
) -> int:
    conn = connect(db_path)

    course_ids = _selected_course_ids(conn, all_courses=all_courses)
    if not course_ids:
        console.print("No courses selected. Run `sync courses` and star courses first, or use --all.")
        return 1

    synced = 0
    people_total = 0
    modules_total = 0
    items_total = 0
    submissions_total = 0
    announcements_total = 0
    pages_total = 0
    files_total = 0
    discussions_total = 0

    with conn:
        for cid in course_ids:
            ok = False

            # 1) course detail
            try:
                detail = client.get_course(
                    cid,
                    include=["term", "course_image", "syllabus_body", "total_students"],
                )
                upsert_course(conn, detail)
                ok = True
            except Exception as e:
                console.print(f"[yellow]Course {cid}: detail fetch failed: {type(e).__name__}: {e}[/yellow]")

            # 2) people (teachers/TAs)
            try:
                people = client.list_course_users(
                    cid,
                    enrollment_types=["teacher", "ta"],
                    include=["enrollments", "email"],
                )
                replace_course_people(conn, cid, people)
                people_total += len(people)
                ok = True
            except Exception as e:
                console.print(f"[yellow]Course {cid}: people fetch failed: {type(e).__name__}: {e}[/yellow]")

            # 3) modules (+ items)
            try:
                modules = client.list_modules(cid, include_items=True)
                replace_course_modules(conn, cid, modules)
                modules_total += len(modules)
                items_total += sum(len(m.get("items") or []) for m in modules)
                ok = True
            except Exception as e:
                console.print(f"[yellow]Course {cid}: modules fetch failed: {type(e).__name__}: {e}[/yellow]")

            # 4) assignments (+ submission snapshot for self when available)
            try:
                asgs = client.list_assignments(cid, include=["submission"])
                for a in asgs:
                    upsert_assignment(conn, cid, a)
                    sub = a.get("submission")
                    if isinstance(sub, dict) and sub:
                        try:
                            upsert_assignment_submission(conn, cid, int(a.get("id")), sub)
                            submissions_total += 1
                        except Exception:
                            pass
                ok = True
            except Exception as e:
                console.print(f"[yellow]Course {cid}: assignments fetch failed: {type(e).__name__}: {e}[/yellow]")

            # 5) quizzes (Canvas returns 404 when quizzes feature disabled)
            try:
                quizzes = client.list_quizzes(cid)
                for q in quizzes:
                    upsert_quiz(conn, cid, q)
                ok = True
            except Exception as e:
                msg = str(e)
                if "404" in msg or "Not Found" in msg:
                    # ignore per-course
                    pass
                else:
                    console.print(f"[yellow]Course {cid}: quizzes fetch failed: {type(e).__name__}: {e}[/yellow]")

            # 6) announcements
            try:
                anns = client.list_announcements(context_codes=[f"course_{cid}"], active_only=False, latest_only=False)
                replace_course_announcements(conn, cid, anns)
                announcements_total += len(anns)
                ok = True
            except Exception as e:
                console.print(f"[yellow]Course {cid}: announcements fetch failed: {type(e).__name__}: {e}[/yellow]")

            # 7) pages
            try:
                pages = client.list_pages(cid)
                replace_course_pages(conn, cid, pages)
                pages_total += len(pages)
                ok = True
            except Exception as e:
                msg = str(e)
                if "404" not in msg and "Not Found" not in msg:
                    console.print(f"[yellow]Course {cid}: pages fetch failed: {type(e).__name__}: {e}[/yellow]")

            # 8) files
            try:
                files = client.list_files(cid)
                replace_course_files(conn, cid, files)
                files_total += len(files)
                ok = True
            except Exception as e:
                msg = str(e)
                if "404" not in msg and "Not Found" not in msg:
                    console.print(f"[yellow]Course {cid}: files fetch failed: {type(e).__name__}: {e}[/yellow]")

            # 9) discussion topics
            try:
                discussions = client.list_discussion_topics(cid)
                replace_course_discussions(conn, cid, discussions)
                discussions_total += len(discussions)
                ok = True
            except Exception as e:
                msg = str(e)
                if "404" not in msg and "Not Found" not in msg:
                    console.print(f"[yellow]Course {cid}: discussions fetch failed: {type(e).__name__}: {e}[/yellow]")

            if ok:
                synced += 1

    t = Table(title=f"Course profiles synced: {synced}/{len(course_ids)}")
    t.add_column("metric")
    t.add_column("count", justify="right")
    t.add_row("people (teacher/ta)", str(people_total))
    t.add_row("modules", str(modules_total))
    t.add_row("module items", str(items_total))
    t.add_row("assignment submissions", str(submissions_total))
    t.add_row("announcements", str(announcements_total))
    t.add_row("pages", str(pages_total))
    t.add_row("files", str(files_total))
    t.add_row("discussions", str(discussions_total))
    console.print(t)

    return 0


def export_profiles_md(
    *,
    db_path: str,
    out_dir: str = "./export/profiles",
    days: int = 30,
    all_courses: bool = False,
) -> int:
    conn = connect(db_path)
    course_ids = _selected_course_ids(conn, all_courses=all_courses)
    if not course_ids:
        console.print("No courses selected. Star some courses first: canvas-agent courses star ...")
        return 1

    now = datetime.now(UTC)
    end = now + timedelta(days=days)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    written = 0
    index_rows: list[dict[str, object]] = []

    for cid in course_ids:
        c = conn.execute(
            """
            SELECT id, name, course_code, workflow_state, start_at, end_at, term_name, syllabus_body, raw_json
            FROM courses WHERE id=?
            """,
            (cid,),
        ).fetchone()
        if not c:
            continue

        raw = json.loads(c["raw_json"] or "{}")

        people = conn.execute(
            """
            SELECT name, role, email FROM course_people
            WHERE course_id=?
            ORDER BY role, sortable_name, name
            """,
            (cid,),
        ).fetchall()

        modules = conn.execute(
            """
            SELECT module_id, name, position, items_count, state, unlock_at
            FROM course_modules WHERE course_id=?
            ORDER BY position, module_id
            """,
            (cid,),
        ).fetchall()

        module_items = conn.execute(
            """
            SELECT module_id, title, type, html_url, position
            FROM course_module_items WHERE course_id=?
            ORDER BY module_id, position, item_id
            """,
            (cid,),
        ).fetchall()

        asg = conn.execute(
            """
            SELECT id, name, due_at, html_url FROM assignments
            WHERE course_id=?
            ORDER BY due_at
            """,
            (cid,),
        ).fetchall()

        quiz = conn.execute(
            """
            SELECT id, title, due_at, unlock_at, lock_at, html_url FROM quizzes
            WHERE course_id=?
            ORDER BY COALESCE(unlock_at, due_at)
            """,
            (cid,),
        ).fetchall()

        subm = conn.execute(
            """
            SELECT assignment_id, workflow_state, submitted_at, score, grade, late, missing, excused
            FROM assignment_submissions WHERE course_id=?
            """,
            (cid,),
        ).fetchall()

        anns = conn.execute(
            """
            SELECT title, posted_at, html_url FROM course_announcements
            WHERE course_id=? ORDER BY COALESCE(posted_at, delayed_post_at) DESC LIMIT 8
            """,
            (cid,),
        ).fetchall()

        pages = conn.execute(
            """
            SELECT title, html_url, updated_at FROM course_pages
            WHERE course_id=? ORDER BY updated_at DESC, title ASC LIMIT 12
            """,
            (cid,),
        ).fetchall()

        files = conn.execute(
            """
            SELECT display_name, content_type, size, modified_at, url FROM course_files
            WHERE course_id=? ORDER BY modified_at DESC, display_name ASC LIMIT 15
            """,
            (cid,),
        ).fetchall()

        discussions = conn.execute(
            """
            SELECT title, posted_at, last_reply_at, html_url FROM course_discussions
            WHERE course_id=? ORDER BY COALESCE(last_reply_at, posted_at) DESC LIMIT 10
            """,
            (cid,),
        ).fetchall()

        missing_count = sum(1 for s in subm if int(s["missing"] or 0) == 1)
        late_count = sum(1 for s in subm if int(s["late"] or 0) == 1)
        submitted_count = sum(1 for s in subm if s["submitted_at"])

        code = (c["course_code"] or f"course-{cid}").replace("/", "-").replace(" ", "_")
        path = out / f"{code}.profile.md"

        lines: list[str] = []
        lines.append(f"# {c['name']}")
        lines.append("")
        lines.append("## Overview")
        lines.append(f"- course_id: {cid}")
        lines.append(f"- course_code: {c['course_code'] or ''}")
        lines.append(f"- term: {c['term_name'] or ''}")
        lines.append(f"- workflow_state: {c['workflow_state'] or ''}")
        lines.append(f"- start_at: {c['start_at'] or ''}")
        lines.append(f"- end_at: {c['end_at'] or ''}")
        lines.append(f"- timezone: {raw.get('time_zone') or ''}")
        lines.append(f"- default_view: {raw.get('default_view') or ''}")
        lines.append(f"- total_students: {raw.get('total_students') or ''}")

        lines.append("")
        lines.append("## People (Teachers / TAs)")
        if people:
            for p in people:
                email = f" <{p['email']}>" if p["email"] else ""
                lines.append(f"- [{p['role'] or 'unknown'}] {p['name'] or ''}{email}")
        else:
            lines.append("- (none synced)")

        lines.append("")
        lines.append("## Modules")
        if modules:
            items_by_module: dict[int, list] = {}
            for it in module_items:
                items_by_module.setdefault(int(it["module_id"]), []).append(it)

            for m in modules:
                lines.append(
                    f"- Module {m['position']}: **{m['name'] or '(untitled)'}** "
                    f"(items={m['items_count'] or 0}, state={m['state'] or ''})"
                )
                for it in items_by_module.get(int(m["module_id"]), [])[:8]:
                    url = f" {it['html_url']}" if it["html_url"] else ""
                    lines.append(f"  - [{it['type'] or ''}] {it['title'] or '(untitled)'}{url}")
                if len(items_by_module.get(int(m["module_id"]), [])) > 8:
                    lines.append("  - ...(truncated)")
        else:
            lines.append("- (none synced)")

        lines.append("")
        lines.append(f"## Upcoming (next {days} days)")
        future_count = 0
        due_7d_count = 0
        seven_day_end = now + timedelta(days=7)

        for a in asg:
            due = parse_canvas_dt(a["due_at"])
            if not due or not (now <= due <= end):
                continue
            url = f" {a['html_url']}" if a["html_url"] else ""
            lines.append(f"- Assignment: {a['name'] or '(untitled)'} — due `{a['due_at']}`{url}")
            future_count += 1
            if now <= due <= seven_day_end:
                due_7d_count += 1

        for q in quiz:
            ref = q["unlock_at"] or q["due_at"]
            dt = parse_canvas_dt(ref)
            if not dt or not (now <= dt <= end):
                continue
            url = f" {q['html_url']}" if q["html_url"] else ""
            lines.append(
                f"- Quiz: {q['title'] or '(untitled)'} — start `{q['unlock_at'] or ''}` due `{q['due_at'] or ''}`{url}"
            )
            future_count += 1
            if now <= dt <= seven_day_end:
                due_7d_count += 1

        if future_count == 0:
            lines.append("- (none in range)")

        # lightweight risk score for weekly load/missing/late pressure
        risk_score = min(100, missing_count * 25 + late_count * 15 + due_7d_count * 5)
        if risk_score >= 60:
            risk_level = "high"
        elif risk_score >= 30:
            risk_level = "medium"
        else:
            risk_level = "low"

        lines.append("")
        lines.append("## Submission snapshot")
        lines.append(f"- submissions_synced: {len(subm)}")
        lines.append(f"- submitted_count: {submitted_count}")
        lines.append(f"- late_count: {late_count}")
        lines.append(f"- missing_count: {missing_count}")

        lines.append("")
        lines.append("## Risk")
        lines.append(f"- risk_score: {risk_score}/100 ({risk_level})")
        lines.append(f"- due_in_7d: {due_7d_count}")

        lines.append("")
        lines.append("## Recent announcements")
        if anns:
            for a in anns:
                url = f" {a['html_url']}" if a["html_url"] else ""
                lines.append(f"- `{a['posted_at'] or ''}` {a['title'] or '(untitled)'}{url}")
        else:
            lines.append("- (none synced)")

        lines.append("")
        lines.append("## Pages index")
        if pages:
            for p in pages:
                url = f" {p['html_url']}" if p["html_url"] else ""
                lines.append(f"- `{p['updated_at'] or ''}` {p['title'] or '(untitled)'}{url}")
        else:
            lines.append("- (none synced)")

        lines.append("")
        lines.append("## Files index")
        if files:
            for f in files:
                url = f" {f['url']}" if f["url"] else ""
                size = f"{f['size']}B" if f["size"] is not None else "?"
                ctype = f["content_type"] or ""
                lines.append(f"- `{f['modified_at'] or ''}` {f['display_name'] or '(unnamed)'} ({ctype}, {size}){url}")
        else:
            lines.append("- (none synced)")

        lines.append("")
        lines.append("## Discussion topics")
        if discussions:
            for d in discussions:
                url = f" {d['html_url']}" if d["html_url"] else ""
                lines.append(
                    f"- `{d['last_reply_at'] or d['posted_at'] or ''}` {d['title'] or '(untitled)'}{url}"
                )
        else:
            lines.append("- (none synced)")

        if c["syllabus_body"]:
            lines.append("")
            lines.append("## Syllabus (raw HTML)")
            lines.append("```html")
            lines.append(str(c["syllabus_body"]))
            lines.append("```")

        path.write_text("\n".join(lines) + "\n")
        written += 1

        index_rows.append(
            {
                "course_id": cid,
                "course_code": c["course_code"] or "",
                "course_name": c["name"] or "",
                "risk_score": risk_score,
                "risk_level": risk_level,
                "due_7d": due_7d_count,
                "missing": missing_count,
                "late": late_count,
                "pages": len(pages),
                "files": len(files),
                "discussions": len(discussions),
                "announcements": len(anns),
                "profile_file": path.name,
            }
        )

    # Global summary index
    idx_path = out / "profiles_index.md"
    idx_lines: list[str] = []
    idx_lines.append("# Canvas Course Profiles Index")
    idx_lines.append("")
    idx_lines.append(f"Generated at: `{datetime.now(UTC).isoformat()}`")
    idx_lines.append("")
    idx_lines.append("## Course summary")
    idx_lines.append("")

    for r in sorted(index_rows, key=lambda x: str(x["course_code"])):
        idx_lines.append(
            f"- **{r['course_code']}** — {r['course_name']} | "
            f"risk `{r['risk_score']}/100 ({r['risk_level']})` | "
            f"due7d `{r['due_7d']}` missing `{r['missing']}` late `{r['late']}` | "
            f"ann `{r['announcements']}` pages `{r['pages']}` files `{r['files']}` discussions `{r['discussions']}` | "
            f"file: `{r['profile_file']}`"
        )

    idx_lines.append("")
    idx_lines.append("## Data availability legend")
    idx_lines.append("- `0` may mean no data, feature disabled, or permission-limited endpoint on Canvas.")
    idx_lines.append("- Prefer comparing across multiple sync runs before treating `0` as definitive.")

    idx_path.write_text("\n".join(idx_lines) + "\n")

    console.print(f"Wrote course profiles: {written} -> {out}")
    console.print(f"Wrote profile index: {idx_path}")
    return 0


def curate_profiles_ai(
    client: CanvasClient,
    *,
    db_path: str,
    out_dir: str = "./export/profiles_ai",
    all_courses: bool = False,
    ai_provider: str = "auto",
    ai_model: str | None = None,
    openai_api_key: str | None = None,
    openai_base_url: str = "https://api.openai.com/v1",
) -> int:
    conn = connect(db_path)
    course_ids = _selected_course_ids(conn, all_courses=all_courses)
    if not course_ids:
        console.print("No courses selected. Star courses first or use --all.")
        return 1

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    adapter = AIAdapter(
        provider=ai_provider,
        model=ai_model,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
    )

    written = 0

    for cid in course_ids:
        c = conn.execute(
            "SELECT id, name, course_code, term_name, syllabus_body, raw_json FROM courses WHERE id=?",
            (cid,),
        ).fetchone()
        if not c:
            continue

        pages = conn.execute(
            "SELECT title, html_url, updated_at FROM course_pages WHERE course_id=? ORDER BY updated_at DESC LIMIT 20",
            (cid,),
        ).fetchall()
        files = conn.execute(
            "SELECT display_name, content_type, modified_at, url FROM course_files WHERE course_id=? ORDER BY modified_at DESC LIMIT 30",
            (cid,),
        ).fetchall()
        anns = conn.execute(
            "SELECT title, posted_at, html_url FROM course_announcements WHERE course_id=? ORDER BY COALESCE(posted_at, '') DESC LIMIT 10",
            (cid,),
        ).fetchall()
        upcoming_asg = conn.execute(
            "SELECT name, due_at, html_url FROM assignments WHERE course_id=? ORDER BY due_at LIMIT 20",
            (cid,),
        ).fetchall()

        syllabus_hint_pages = [
            f"- {p['title']} ({p['html_url'] or ''})"
            for p in pages
            if (p["title"] or "").lower().find("syll") != -1
        ]
        syllabus_hint_files = [
            f"- {f['display_name']} ({f['url'] or ''})"
            for f in files
            if any(k in (f["display_name"] or "").lower() for k in ["syll", "outline", "course info"])
        ]

        front_page_title = ""
        front_page_body = ""
        front_page_syllabus_links: list[str] = []
        try:
            fp = client.get_front_page(int(cid))
            front_page_title = str(fp.get("title") or "")
            front_page_body = str(fp.get("body") or "")
            for href in re.findall(r'href="([^"]+)"', front_page_body):
                h = href.replace("&amp;", "&")
                if any(k in h.lower() for k in ["syll", "outline", "file", "files/"]):
                    front_page_syllabus_links.append(h)
            front_page_syllabus_links = list(dict.fromkeys(front_page_syllabus_links))[:12]
        except Exception:
            pass

        prompt = "\n".join(
            [
                "You are organizing a Canvas course archive.",
                "Task: identify the most likely syllabus source and output a structured course dossier in markdown.",
                "Use this template exactly:\n",
                "# <course name>",
                "## Syllabus Source",
                "- Primary: ...",
                "- Why: ...",
                "## Course Structure",
                "- Goals: ...",
                "- Policies: ...",
                "- Grading: ...",
                "## Key Logistics",
                "- Instructors/TAs: ...",
                "- Important links: ...",
                "## Upcoming Priorities",
                "- [ ] ...",
                "## Questions to Clarify",
                "- ...",
                "",
                f"Course: {c['name']} ({c['course_code']}) term={c['term_name']}",
                "",
                "Syllabus HTML (may be empty):",
                (c["syllabus_body"] or "(empty)")[:6000],
                "",
                f"Front page title: {front_page_title or '(unknown)'}",
                "Front page snippet:",
                (front_page_body[:5000] if front_page_body else "(empty/unavailable)"),
                "",
                "Potential syllabus links found on front page:",
                *([f"- {u}" for u in front_page_syllabus_links] or ["- (none)"]),
                "",
                "Possible syllabus pages:",
                *(syllabus_hint_pages or ["- (none)"]),
                "",
                "Possible syllabus files:",
                *(syllabus_hint_files or ["- (none)"]),
                "",
                "Recent announcements:",
                *[
                    f"- {a['posted_at'] or ''} | {a['title'] or ''} | {a['html_url'] or ''}"
                    for a in anns
                ],
                "",
                "Upcoming assignments:",
                *[
                    f"- {a['due_at'] or ''} | {a['name'] or ''} | {a['html_url'] or ''}"
                    for a in upcoming_asg
                ],
            ]
        )

        try:
            curated = adapter.complete(prompt)
        except AIAdapterError as e:
            curated = f"# {c['name']}\n\nAI curation failed: {e}\n"

        safe = (c["course_code"] or f"course-{cid}").replace("/", "-").replace(" ", "_")
        path = out / f"{safe}.curated.md"
        path.write_text(curated.strip() + "\n")
        written += 1

    console.print(f"Wrote AI-curated dossiers: {written} -> {out}")
    return 0
