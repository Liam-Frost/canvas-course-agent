from __future__ import annotations

import httpx


def discord_send(*, webhook_url: str, content: str) -> None:
    if not webhook_url:
        raise SystemExit("DISCORD_WEBHOOK_URL is not set")

    with httpx.Client(timeout=30.0) as c:
        r = c.post(webhook_url, json={"content": content})
        r.raise_for_status()
