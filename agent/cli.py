from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from .config import Settings
from .providers.canvas import CanvasClient
from .sync import sync_calendar, sync_courses

console = Console()


def load_settings() -> Settings:
    # When executed via heredoc / embedded contexts, python-dotenv can mis-detect paths.
    # Be explicit.
    load_dotenv(dotenv_path=".env")
    return Settings(
        canvas_base_url=os.getenv("CANVAS_BASE_URL", "https://canvas.ubc.ca"),
        canvas_access_token=os.getenv("CANVAS_ACCESS_TOKEN", ""),
        db_path=os.getenv("DB_PATH", "./data/agent.db"),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
    )


def canvas_client(s: Settings) -> CanvasClient:
    if not s.canvas_access_token:
        raise SystemExit("CANVAS_ACCESS_TOKEN is not set")
    return CanvasClient(base_url=s.canvas_base_url, access_token=s.canvas_access_token)


def cmd_healthcheck() -> int:
    s = load_settings()
    console.print("canvas_base_url:", s.canvas_base_url)
    console.print("db_path:", s.db_path)
    console.print("discord_webhook_url set:", bool(s.discord_webhook_url))

    if not s.canvas_access_token:
        console.print("[yellow]CANVAS_ACCESS_TOKEN not set (expected for real API calls).[/yellow]")

    Path(s.db_path).parent.mkdir(parents=True, exist_ok=True)
    console.print("[green]OK[/green]")
    return 0


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(prog="canvas-agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("healthcheck")

    sp_sync = sub.add_parser("sync")
    sub_sync = sp_sync.add_subparsers(dest="sync_cmd", required=True)

    sub_sync.add_parser("courses")

    p_cal = sub_sync.add_parser("calendar")
    p_cal.add_argument("--days", type=int, default=14)

    args = p.parse_args()
    if args.cmd == "healthcheck":
        raise SystemExit(cmd_healthcheck())

    if args.cmd == "sync":
        s = load_settings()
        client = canvas_client(s)
        if args.sync_cmd == "courses":
            raise SystemExit(sync_courses(client, db_path=s.db_path))
        if args.sync_cmd == "calendar":
            raise SystemExit(sync_calendar(client, db_path=s.db_path, days=args.days))

    raise SystemExit(2)
