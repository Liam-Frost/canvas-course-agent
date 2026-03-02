from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .storage.sqlite import connect, get_setting, set_setting

console = Console()


KNOWN_KEYS = {
    "filter.assignments": "on|off",
}


def cmd_config_show(*, db_path: str) -> int:
    conn = connect(db_path)
    t = Table(title="Config")
    t.add_column("key")
    t.add_column("value")

    # show known keys first
    for k in sorted(KNOWN_KEYS.keys()):
        v = get_setting(conn, k, default="") or ""
        t.add_row(k, v)

    console.print(t)
    console.print("Use: canvas-agent config set <key> <value>")
    return 0


def cmd_config_set(key: str, value: str, *, db_path: str) -> int:
    if key in KNOWN_KEYS:
        if value not in {"on", "off"}:
            raise SystemExit(f"{key} expects on|off")
    conn = connect(db_path)
    with conn:
        set_setting(conn, key, value)
    console.print(f"Set {key}={value}")
    return 0
