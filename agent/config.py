from __future__ import annotations

from pydantic import BaseModel, Field


class Settings(BaseModel):
    canvas_base_url: str = Field(default="https://canvas.ubc.ca")
    canvas_access_token: str = Field(default="")
    db_path: str = Field(default="./data/agent.db")
    discord_webhook_url: str | None = Field(default=None)
    telegram_bot_token: str | None = Field(default=None)
    timezone: str = Field(default="UTC")

    # AI adapter (phase 1)
    ai_provider: str = Field(default="auto")
    ai_model: str | None = Field(default=None)
    openai_api_key: str | None = Field(default=None)
    openai_base_url: str = Field(default="https://api.openai.com/v1")

    # Syllabus detection strategy
    syllabus_link_keywords: str = Field(default="syll,outline,course info,grading,schedule")

    # Course label display mode
    course_label_short: bool = Field(default=False)
