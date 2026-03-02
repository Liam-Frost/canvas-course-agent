from __future__ import annotations

from pydantic import BaseModel, Field


class Settings(BaseModel):
    canvas_base_url: str = Field(default="https://canvas.ubc.ca")
    canvas_access_token: str = Field(default="")
    db_path: str = Field(default="./data/agent.db")
    discord_webhook_url: str | None = Field(default=None)
