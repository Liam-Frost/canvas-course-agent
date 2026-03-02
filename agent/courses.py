from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .storage.sqlite import connect, is_starred, list_courses, star_course, unstar_course

console = Console()


def cmd_courses_list(*, db_path: str, term_like: str | None = None) -> int:
    conn = connect(db_path)
    rows = list_courses(conn)
    if term_like:
        tl = term_like.lower()
        rows = [r for r in rows if (str(r["term_name"] or "").lower().find(tl) != -1)]

    t = Table(title=f"Courses ({len(rows)})")
    t.add_column("#", justify="right")
    t.add_column("⭐")
    t.add_column("course_id", justify="right")
    t.add_column("code")
    t.add_column("name")
    t.add_column("term")

    for i, r in enumerate(rows, start=1):
        starred = is_starred(conn, int(r["id"]))
        t.add_row(
            str(i),
            "⭐" if starred else "",
            str(r["id"]),
            str(r["course_code"] or ""),
            str(r["name"] or ""),
            str(r["term_name"] or ""),
        )

    console.print(t)
    console.print("Use: canvas-agent courses star <#...> | unstar <#...>")
    console.print("Also: canvas-agent courses star --by-code CPEN 212")
    return 0


def _resolve_indices(indices: list[int], *, db_path: str, term_like: str | None = None) -> list[int]:
    conn = connect(db_path)
    rows = list_courses(conn)
    if term_like:
        tl = term_like.lower()
        rows = [r for r in rows if (str(r["term_name"] or "").lower().find(tl) != -1)]
    out: list[int] = []
    for idx in indices:
        if idx < 1 or idx > len(rows):
            raise SystemExit(f"Index out of range: {idx} (1..{len(rows)})")
        out.append(int(rows[idx - 1]["id"]))
    return out


def _match_by_code(conn, tokens: list[str], term_like: str | None = None) -> list[int]:
    rows = list_courses(conn)
    if term_like:
        tl = term_like.lower()
        rows = [r for r in rows if (str(r["term_name"] or "").lower().find(tl) != -1)]

    toks = [t.lower() for t in tokens if t.strip()]
    matched: list[int] = []
    for r in rows:
        hay = f"{r['course_code'] or ''} {r['name'] or ''}".lower()
        if all(t in hay for t in toks):
            matched.append(int(r["id"]))
    return matched


def cmd_courses_star(
    indices: list[int] | None,
    *,
    db_path: str,
    by_code: list[str] | None = None,
    term_like: str | None = None,
) -> int:
    conn0 = connect(db_path)
    if by_code:
        course_ids = _match_by_code(conn0, by_code, term_like=term_like)
        if not course_ids:
            raise SystemExit(f"No courses matched by-code tokens: {by_code}")
    else:
        if not indices:
            raise SystemExit("Provide indices or --by-code tokens")
        course_ids = _resolve_indices(indices, db_path=db_path, term_like=term_like)
    conn = connect(db_path)
    with conn:
        for cid in course_ids:
            star_course(conn, cid)
    console.print(f"Starred {len(course_ids)} course(s): {course_ids}")
    return 0


def cmd_courses_unstar(indices: list[int], *, db_path: str, term_like: str | None = None) -> int:
    course_ids = _resolve_indices(indices, db_path=db_path, term_like=term_like)
    conn = connect(db_path)
    with conn:
        for cid in course_ids:
            unstar_course(conn, cid)
    console.print(f"Unstarred {len(course_ids)} course(s): {course_ids}")
    return 0
