from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from .config import Settings
from .config_cmd import cmd_config_set, cmd_config_show
from .courses import cmd_courses_list, cmd_courses_star, cmd_courses_unstar
from .providers.canvas import CanvasClient
from .sync import sync_calendar, sync_courses
from .sync_items import sync_assignments, sync_quizzes
from .init_wizard import run_init
from .upcoming import upcoming

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
        timezone=os.getenv("TIMEZONE", "UTC"),
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

    p = argparse.ArgumentParser(prog="canvas-agent", description="Canvas Course Agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("help")
    sub.add_parser("healthcheck")

    sp_config = sub.add_parser("config")
    sub_config = sp_config.add_subparsers(dest="config_cmd", required=True)
    sub_config.add_parser("show")
    p_set = sub_config.add_parser("set")
    p_set.add_argument("key")
    p_set.add_argument("value")

    sp_courses = sub.add_parser("courses")
    sub_courses = sp_courses.add_subparsers(dest="courses_cmd", required=True)

    p_list = sub_courses.add_parser("list")
    p_list.add_argument("--term-like", default=None)

    p_star = sub_courses.add_parser("star")
    p_star.add_argument("--term-like", default=None)
    p_star.add_argument("--by-code", nargs="+", default=None, help="tokens matched against course_code+name")
    p_star.add_argument("indices", nargs="*", type=int, help="course indices from 'courses list'")

    p_unstar = sub_courses.add_parser("unstar")
    p_unstar.add_argument("--term-like", default=None)
    p_unstar.add_argument("indices", nargs="+", type=int)

    sub.add_parser("init")

    p_up = sub.add_parser("upcoming")
    p_up.add_argument("--days", type=int, default=14)
    p_up.add_argument("--all", action="store_true")

    sp_sync = sub.add_parser("sync")
    sub_sync = sp_sync.add_subparsers(dest="sync_cmd", required=True)

    sub_sync.add_parser("courses")

    p_cal = sub_sync.add_parser("calendar")
    p_cal.add_argument("--days", type=int, default=14)
    p_cal.add_argument("--all", action="store_true", help="ignore starred filter and fetch all")
    p_cal.add_argument("--type", default=None, help="assignment|event (optional)")

    p_asg = sub_sync.add_parser("assignments")
    p_asg.add_argument("--days", type=int, default=14)
    p_asg.add_argument("--all", action="store_true")
    p_asg.add_argument("--no-filter", action="store_true", help="disable noise filtering")

    p_qz = sub_sync.add_parser("quizzes")
    p_qz.add_argument("--days", type=int, default=14)
    p_qz.add_argument("--all", action="store_true")

    args = p.parse_args()
    if args.cmd == "help":
        p.print_help()
        raise SystemExit(0)

    if args.cmd == "healthcheck":
        raise SystemExit(cmd_healthcheck())

    if args.cmd == "config":
        s = load_settings()
        if args.config_cmd == "show":
            raise SystemExit(cmd_config_show(db_path=s.db_path))
        if args.config_cmd == "set":
            raise SystemExit(cmd_config_set(args.key, args.value, db_path=s.db_path))

    if args.cmd == "courses":
        s = load_settings()
        if args.courses_cmd == "list":
            raise SystemExit(cmd_courses_list(db_path=s.db_path, term_like=args.term_like))
        if args.courses_cmd == "star":
            raise SystemExit(
                cmd_courses_star(
                    args.indices or None,
                    db_path=s.db_path,
                    by_code=args.by_code,
                    term_like=args.term_like,
                )
            )
        if args.courses_cmd == "unstar":
            raise SystemExit(cmd_courses_unstar(args.indices, db_path=s.db_path, term_like=args.term_like))

    if args.cmd == "init":
        raise SystemExit(run_init(env_path=".env"))

    if args.cmd == "upcoming":
        s = load_settings()
        raise SystemExit(upcoming(db_path=s.db_path, days=args.days, all_courses=args.all, timezone=s.timezone))

    if args.cmd == "sync":
        s = load_settings()
        client = canvas_client(s)
        if args.sync_cmd == "courses":
            raise SystemExit(sync_courses(client, db_path=s.db_path))
        if args.sync_cmd == "calendar":
            raise SystemExit(
                sync_calendar(
                    client,
                    db_path=s.db_path,
                    days=args.days,
                    all_courses=args.all,
                    type=args.type,
                    timezone=s.timezone,
                )
            )
        if args.sync_cmd == "assignments":
            raise SystemExit(
                sync_assignments(
                    client,
                    db_path=s.db_path,
                    days=args.days,
                    all_courses=args.all,
                    timezone=s.timezone,
                    no_filter=args.no_filter,
                )
            )
        if args.sync_cmd == "quizzes":
            raise SystemExit(
                sync_quizzes(
                    client,
                    db_path=s.db_path,
                    days=args.days,
                    all_courses=args.all,
                    timezone=s.timezone,
                )
            )

    raise SystemExit(2)
