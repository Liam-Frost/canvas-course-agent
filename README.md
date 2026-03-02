# Canvas Course Agent

A personal agent that pulls course info from Canvas (syllabus/assignments/quizzes/calendar) and turns it into a local course archive + reminders (e.g. Discord).

## Goals (v0)
- Import courses + key metadata
- Import deadlines (assignments/quizzes) via Canvas APIs
- Store locally (SQLite)
- Send reminders to Discord

## Configuration
This project is **multi-school** by design.

Set env vars (recommended via `.env`):

- `CANVAS_BASE_URL` (e.g. `https://canvas.ubc.ca`)
- `CANVAS_ACCESS_TOKEN` (Canvas API token)
- `DB_PATH` (default: `./data/agent.db`)
- `DISCORD_WEBHOOK_URL` (optional for v0; later we can switch to a bot)

## Dev quickstart
```bash
cd canvas-course-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
cp .env.example .env
# edit .env
canvas-agent healthcheck
```

## Security
Treat `CANVAS_ACCESS_TOKEN` like a password. Do not commit it.
