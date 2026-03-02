# Canvas Course Agent

A personal agent that pulls course info from Canvas (syllabus/assignments/quizzes/calendar) and turns it into a local course archive + reminders (e.g. Discord).

This is meant to work with **any** Canvas instance (e.g. `https://canvas.ubc.ca`) via config.

## What it does (v0 scope)
- Import your course list
- Import deadlines (assignments/quizzes/calendar items)
- Let you pick “important courses” (starred) and only sync/remind for those
- Store locally (SQLite)
- Send reminders to Discord (webhook for now)

## Configuration
This project is **multi-school** by design.

Set env vars (recommended via `.env`):

- `CANVAS_BASE_URL` (e.g. `https://canvas.ubc.ca`)
- `CANVAS_ACCESS_TOKEN` (Canvas API token)
- `DB_PATH` (default: `./data/agent.db`)
- `TIMEZONE` (IANA timezone for display, e.g. `America/Vancouver`)
- `DISCORD_WEBHOOK_URL` (optional for v0; later we can switch to a bot)

Example (`.env`):
```bash
CANVAS_BASE_URL=https://canvas.ubc.ca
CANVAS_ACCESS_TOKEN=...
DB_PATH=./data/agent.db
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

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

## First-time setup
Run the init wizard to generate `.env`:
```bash
canvas-agent init
```

## Basic usage
Helpful commands:
```bash
canvas-agent help
canvas-agent healthcheck
```

1) Sync courses:
```bash
canvas-agent sync courses
```

2) List and star important courses:
```bash
canvas-agent courses list
canvas-agent courses star 1 2 3
canvas-agent courses unstar 3
```

3) Sync items (defaults to ⭐ courses only):
```bash
canvas-agent sync assignments --days 14
canvas-agent sync quizzes --days 14
canvas-agent sync calendar --days 14
```

4) Show upcoming (merged view):
```bash
canvas-agent upcoming --days 14
```

If you want to fetch for all courses (debug):
```bash
canvas-agent sync assignments --days 14 --all
```

## How to get a Canvas token
For personal use/testing you can generate an access token in Canvas:
- Profile → Approved Integrations → New Access Token

Treat it like a password.

## GitHub workflow
We use GitHub CLI (`gh`) on the VPS.

Authenticate once:
```bash
gh auth login
```

Then create/push repos from the terminal.

## License
MIT

## Security
Treat `CANVAS_ACCESS_TOKEN` like a password. Do not commit it.
