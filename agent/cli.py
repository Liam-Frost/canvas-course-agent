from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from .config import Settings

console = Console()


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        canvas_base_url=os.getenv("CANVAS_BASE_URL", "https://canvas.ubc.ca"),
        canvas_access_token=os.getenv("CANVAS_ACCESS_TOKEN", ""),
        db_path=os.getenv("DB_PATH", "./data/agent.db"),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
    )


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

    args = p.parse_args()
    if args.cmd == "healthcheck":
        raise SystemExit(cmd_healthcheck())
