from __future__ import annotations

import re


def short_course_label(name: str, course_code: str | None) -> str:
    """Try to derive compact label like 'CPEN 212' from Canvas course_code/name."""
    cc = (course_code or "").strip()
    m = re.search(r"([A-Za-z]{2,6})\s*[_\- ]?\s*V?\s*(\d{2,4})", cc)
    if m:
        return f"{m.group(1).upper()} {m.group(2)}"

    n = (name or "").strip()
    m2 = re.search(r"\b([A-Za-z]{2,6})\s*[_\- ]?\s*V?\s*(\d{2,4})\b", n)
    if m2:
        return f"{m2.group(1).upper()} {m2.group(2)}"

    return cc if cc else n


def format_course_label(name: str, course_code: str | None, *, short_enabled: bool) -> str:
    if short_enabled:
        return short_course_label(name, course_code)
    return (name or course_code or "").strip()
