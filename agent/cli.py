from __future__ import annotations

import os
import subprocess
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from .config import Settings
from .config_cmd import cmd_config_set, cmd_config_show
from .courses import cmd_courses_list, cmd_courses_star, cmd_courses_unstar
from .providers.canvas import CanvasClient
from .sync import sync_calendar, sync_courses
from .sync_items import sync_assignments, sync_quizzes
from .digest import cmd_digest
from .export_cmd import export_ics, export_md
from .init_wizard import run_init
from .remind import remind_run
from .remind_custom import cmd_remind_add, cmd_remind_disable, cmd_remind_list
from .telegram_cmd import telegram_link
from .upcoming import upcoming
from .profile import sync_profiles, export_profiles_md
from .ai_adapter import AIAdapter, AIAdapterError

console = Console()


def load_settings(env_path: str) -> Settings:
    # When executed via heredoc / embedded contexts, python-dotenv can mis-detect paths.
    # Be explicit.
    load_dotenv(dotenv_path=env_path)
    return Settings(
        canvas_base_url=os.getenv("CANVAS_BASE_URL", "https://canvas.ubc.ca"),
        canvas_access_token=os.getenv("CANVAS_ACCESS_TOKEN", ""),
        db_path=os.getenv("DB_PATH", "./data/agent.db"),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        timezone=os.getenv("TIMEZONE", "UTC"),
        ai_provider=os.getenv("AI_PROVIDER", "auto"),
        ai_model=os.getenv("AI_MODEL") or None,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )


def canvas_client(s: Settings) -> CanvasClient:
    if not s.canvas_access_token:
        raise SystemExit("CANVAS_ACCESS_TOKEN is not set")
    return CanvasClient(base_url=s.canvas_base_url, access_token=s.canvas_access_token)


def cmd_healthcheck(env_path: str) -> int:
    s = load_settings(env_path)
    console.print("canvas_base_url:", s.canvas_base_url)
    console.print("db_path:", s.db_path)
    console.print("discord_webhook_url set:", bool(s.discord_webhook_url))
    console.print("ai_provider:", s.ai_provider)
    console.print("ai_model:", s.ai_model or "(default)")
    console.print("openai_api_key set:", bool(s.openai_api_key))

    if not s.canvas_access_token:
        console.print("[yellow]CANVAS_ACCESS_TOKEN not set (expected for real API calls).[/yellow]")

    Path(s.db_path).parent.mkdir(parents=True, exist_ok=True)
    console.print("[green]OK[/green]")
    return 0


def _upsert_env(env_path: str, key: str, value: str) -> None:
    p = Path(env_path)
    lines: list[str] = []
    if p.exists():
        lines = p.read_text().splitlines()

    replaced = False
    out: list[str] = []
    for ln in lines:
        if ln.startswith(f"{key}="):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(ln)

    if not replaced:
        out.append(f"{key}={value}")

    p.write_text("\n".join(out) + "\n")


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(prog="canvas-agent", description="Canvas Course Agent")
    p.add_argument(
        "--env-path",
        default=os.getenv("CANVAS_AGENT_ENV", ".env"),
        help="Path to .env file (default: .env or CANVAS_AGENT_ENV)",
    )
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

    sp_telegram = sub.add_parser("telegram")
    sub_tg = sp_telegram.add_subparsers(dest="telegram_cmd", required=True)
    sub_tg.add_parser("link")

    sp_remind = sub.add_parser("remind")
    sub_remind = sp_remind.add_subparsers(dest="remind_cmd", required=True)

    p_add = sub_remind.add_parser("add")
    p_add.add_argument("--title", required=True)
    g = p_add.add_mutually_exclusive_group(required=True)
    g.add_argument("--at", help='local time in TIMEZONE, e.g. "2026-03-05 13:00"')
    g.add_argument("--in", dest="in_", help='relative time, e.g. 90m or 2h')
    p_add.add_argument("--channels", default="discord,telegram")
    p_add.add_argument("--silent", action="store_true", help="telegram only")

    sub_remind.add_parser("list")

    p_dis = sub_remind.add_parser("disable")
    p_dis.add_argument("id", type=int)

    p_run = sub_remind.add_parser("run")
    p_run.add_argument("--lookahead-min", type=int, default=2)
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--send-discord", action="store_true")
    p_run.add_argument("--send-telegram", action="store_true")

    p_digest = sub.add_parser("digest")
    p_digest.add_argument("--days", type=int, default=7)
    p_digest.add_argument("--all", action="store_true")
    p_digest.add_argument("--send-discord", action="store_true")

    sp_export = sub.add_parser("export")
    sub_export = sp_export.add_subparsers(dest="export_cmd", required=True)

    p_ics = sub_export.add_parser("ics")
    p_ics.add_argument("--days", type=int, default=30)
    p_ics.add_argument("--all", action="store_true")
    p_ics.add_argument("--out", default="./export/canvas.ics")

    p_md = sub_export.add_parser("md")
    p_md.add_argument("--days", type=int, default=30)
    p_md.add_argument("--all", action="store_true")
    p_md.add_argument("--out-dir", default="./export/md")

    p_up = sub.add_parser("upcoming")
    p_up.add_argument("--days", type=int, default=14)
    p_up.add_argument("--all", action="store_true")

    sp_ai = sub.add_parser("ai")
    sub_ai = sp_ai.add_subparsers(dest="ai_cmd", required=True)

    p_ai_probe = sub_ai.add_parser("probe", help="probe AI adapter with a test prompt")
    p_ai_probe.add_argument("--provider", choices=["auto", "codex-oauth", "openai-api"], default=None)
    p_ai_probe.add_argument("--model", default=None)
    p_ai_probe.add_argument("--prompt", default="Say OK")

    p_ai_doctor = sub_ai.add_parser("doctor", help="show adapter/auth readiness diagnostics")
    p_ai_doctor.add_argument("--provider", choices=["auto", "codex-oauth", "openai-api"], default=None)
    p_ai_doctor.add_argument("--model", default=None)

    p_ai_auth = sub_ai.add_parser("auth", help="project-local auth setup flow")
    p_ai_auth.add_argument("--provider", choices=["codex-oauth", "openai-api"], required=True)

    sp_profile = sub.add_parser("profile")
    sub_profile = sp_profile.add_subparsers(dest="profile_cmd", required=True)

    p_profile_sync = sub_profile.add_parser("sync")
    p_profile_sync.add_argument("--all", action="store_true", help="ignore starred filter and sync all")

    p_profile_export = sub_profile.add_parser("export")
    p_profile_export.add_argument("--days", type=int, default=30)
    p_profile_export.add_argument("--all", action="store_true")
    p_profile_export.add_argument("--out-dir", default="./export/profiles")

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
    env_path = args.env_path
    if args.cmd == "help":
        p.print_help()
        raise SystemExit(0)

    if args.cmd == "healthcheck":
        raise SystemExit(cmd_healthcheck(env_path))

    if args.cmd == "config":
        s = load_settings(env_path)
        if args.config_cmd == "show":
            raise SystemExit(cmd_config_show(db_path=s.db_path))
        if args.config_cmd == "set":
            raise SystemExit(cmd_config_set(args.key, args.value, db_path=s.db_path))

    if args.cmd == "courses":
        s = load_settings(env_path)
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
        raise SystemExit(run_init(env_path=env_path))

    if args.cmd == "telegram":
        s = load_settings(env_path)
        if args.telegram_cmd == "link":
            raise SystemExit(telegram_link(db_path=s.db_path, bot_token=s.telegram_bot_token or ""))

    if args.cmd == "remind":
        s = load_settings(env_path)
        if args.remind_cmd == "add":
            raise SystemExit(
                cmd_remind_add(
                    db_path=s.db_path,
                    timezone=s.timezone,
                    title=args.title,
                    at=args.at,
                    in_=args.in_,
                    channels=args.channels,
                    silent=args.silent,
                )
            )
        if args.remind_cmd == "list":
            raise SystemExit(cmd_remind_list(db_path=s.db_path, timezone=s.timezone))
        if args.remind_cmd == "disable":
            raise SystemExit(cmd_remind_disable(db_path=s.db_path, reminder_id=args.id))

        if args.remind_cmd == "run":
            # default dry-run unless explicit send
            dry = True
            if args.send_discord or args.send_telegram:
                dry = False
            if args.dry_run:
                dry = True

            raise SystemExit(
                remind_run(
                    db_path=s.db_path,
                    timezone=s.timezone,
                    lookahead_min=args.lookahead_min,
                    send_discord=args.send_discord,
                    send_telegram=args.send_telegram,
                    dry_run=dry,
                    discord_webhook_url=s.discord_webhook_url,
                    telegram_bot_token=s.telegram_bot_token,
                )
            )

    if args.cmd == "digest":
        s = load_settings(env_path)
        raise SystemExit(
            cmd_digest(
                db_path=s.db_path,
                days=args.days,
                all_courses=args.all,
                timezone=s.timezone,
                discord_webhook_url=s.discord_webhook_url,
                send_discord=args.send_discord,
            )
        )

    if args.cmd == "export":
        s = load_settings(env_path)
        if args.export_cmd == "ics":
            raise SystemExit(export_ics(db_path=s.db_path, out_path=args.out, days=args.days, all_courses=args.all))
        if args.export_cmd == "md":
            raise SystemExit(export_md(db_path=s.db_path, out_dir=args.out_dir, days=args.days, all_courses=args.all))

    if args.cmd == "upcoming":
        s = load_settings(env_path)
        raise SystemExit(upcoming(db_path=s.db_path, days=args.days, all_courses=args.all, timezone=s.timezone))

    if args.cmd == "ai":
        s = load_settings(env_path)
        provider = args.provider or s.ai_provider
        model = getattr(args, "model", None) or s.ai_model
        adapter = AIAdapter(
            provider=provider,
            model=model,
            openai_api_key=s.openai_api_key,
            openai_base_url=s.openai_base_url,
        )

        if args.ai_cmd == "doctor":
            for line in adapter.doctor():
                console.print("-", line)
            raise SystemExit(0)

        if args.ai_cmd == "auth":
            if args.provider == "openai-api":
                console.print("Enter OPENAI_API_KEY (input hidden):")
                key = getpass("").strip()
                if not key:
                    console.print("[red]No key entered.[/red]")
                    raise SystemExit(1)
                _upsert_env(env_path, "OPENAI_API_KEY", key)
                _upsert_env(env_path, "AI_PROVIDER", "auto")
                console.print(f"[green]Saved OPENAI_API_KEY to {env_path} and set AI_PROVIDER=auto[/green]")
                raise SystemExit(0)

            if args.provider == "codex-oauth":
                console.print("Starting codex oauth flow...")
                console.print("1) A login URL will appear.")
                console.print("2) Open it in browser and sign in.")
                console.print("3) If prompted, paste the final redirected URL back into this terminal.")
                cp = subprocess.run(["codex", "login"], check=False)
                if cp.returncode != 0:
                    console.print("[red]codex login failed.[/red]")
                    raise SystemExit(cp.returncode)
                _upsert_env(env_path, "AI_PROVIDER", "auto")
                console.print(f"[green]codex oauth login complete. Set AI_PROVIDER=auto in {env_path}[/green]")
                raise SystemExit(0)

        if args.ai_cmd == "probe":
            try:
                out = adapter.complete(args.prompt)
                console.print(out)
                raise SystemExit(0)
            except AIAdapterError as e:
                console.print(f"[red]AI probe failed:[/red] {e}")
                raise SystemExit(1)

    if args.cmd == "profile":
        s = load_settings(env_path)
        if args.profile_cmd == "sync":
            client = canvas_client(s)
            raise SystemExit(sync_profiles(client, db_path=s.db_path, all_courses=args.all))
        if args.profile_cmd == "export":
            raise SystemExit(
                export_profiles_md(
                    db_path=s.db_path,
                    out_dir=args.out_dir,
                    days=args.days,
                    all_courses=args.all,
                )
            )

    if args.cmd == "sync":
        s = load_settings(env_path)
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
