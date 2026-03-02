from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .storage.sqlite import connect, is_starred, list_courses, star_course, unstar_course

console = Console()


def cmd_courses_list(*, db_path: str) -> int:
    conn = connect(db_path)
    rows = list_courses(conn)

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
    return 0


def _resolve_indices(indices: list[int], *, db_path: str) -> list[int]:
    conn = connect(db_path)
    rows = list_courses(conn)
    out: list[int] = []
    for idx in indices:
        if idx < 1 or idx > len(rows):
            raise SystemExit(f"Index out of range: {idx} (1..{len(rows)})")
        out.append(int(rows[idx - 1]["id"]))
    return out


def cmd_courses_star(indices: list[int], *, db_path: str) -> int:
    course_ids = _resolve_indices(indices, db_path=db_path)
    conn = connect(db_path)
    with conn:
        for cid in course_ids:
            star_course(conn, cid)
    console.print(f"Starred {len(course_ids)} course(s): {course_ids}")
    return 0


def cmd_courses_unstar(indices: list[int], *, db_path: str) -> int:
    course_ids = _resolve_indices(indices, db_path=db_path)
    conn = connect(db_path)
    with conn:
        for cid in course_ids:
            unstar_course(conn, cid)
    console.print(f"Unstarred {len(course_ids)} course(s): {course_ids}")
    return 0
