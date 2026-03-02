from __future__ import annotations

import httpx
from rich.console import Console

from .storage.sqlite import connect, set_setting

console = Console()


def telegram_link(*, db_path: str, bot_token: str) -> int:
    """Fetch latest Telegram updates to discover chat_id and store it in DB settings."""
    if not bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    with httpx.Client(timeout=30.0) as c:
        r = c.get(url, params={"timeout": 0, "allowed_updates": ["message"]})
        r.raise_for_status()
        data = r.json()

    if not data.get("ok"):
        raise SystemExit(f"Telegram getUpdates failed: {data}")

    updates = data.get("result") or []
    if not updates:
        raise SystemExit("No updates found. Send /start to your bot in Telegram, then run again.")

    # Pick the newest message update with a chat id.
    chat_id = None
    username = None
    for upd in reversed(updates):
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            chat_id = chat.get("id")
            username = chat.get("username")
            break

    if chat_id is None:
        raise SystemExit("No message.chat.id found in updates. Try sending /start again.")

    conn = connect(db_path)
    with conn:
        set_setting(conn, "telegram.chat_id", str(chat_id))

    console.print(f"[green]Saved telegram.chat_id={chat_id}[/green]")
    if username:
        console.print(f"Telegram username: @{username}")

    return 0


def telegram_send(*, bot_token: str, chat_id: str, text: str, silent: bool = False) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if silent:
        payload["disable_notification"] = True

    with httpx.Client(timeout=30.0) as c:
        r = c.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data}")
