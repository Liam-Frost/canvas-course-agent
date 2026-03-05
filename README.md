# Canvas Course Agent

An **AI Agent for Canvas** that continuously syncs course data (deadlines, submissions, announcements, pages/files/discussions), builds per-course dossiers, and uses an AI backend (Codex OAuth or OpenAI API) to curate structured study archives around each course syllabus. The agent is designed to answer the practical question: *"What matters this week for each course, based on the actual course materials?"* — not just list due dates.

This project is designed to work with **any** Canvas instance (e.g. `https://canvas.ubc.ca`) via config.

## What it does (current scope)
- Import course list + deadline signals (assignments/quizzes/calendar)
- Build per-course profiles in local SQLite:
  - people (teachers/TAs)
  - submissions snapshot (missing/late/score state)
  - announcements
  - modules/module items
  - pages/files/discussion indexes (when Canvas permissions/features allow)
- Compute lightweight risk score per course and generate a global `profiles_index.md`
- Let you star important courses and filter sync/reminders by star set
- Export iCalendar (.ics) and Markdown profiles
- AI adapter entrypoint (`canvas-agent ai ...`) with:
  - `auto` routing
  - `codex-oauth` backend
  - `openai-api` backend
- AI global-state snapshot (`canvas-agent profile state`) to infer active term, current teaching week, and exam timeline
- Send reminders/digest to Discord (webhook) and Telegram

## Configuration
This project is **multi-school** by design.

Set env vars (recommended via `.env`):

- `CANVAS_BASE_URL` (e.g. `https://canvas.ubc.ca`)
- `CANVAS_ACCESS_TOKEN` (Canvas API token)
- `DB_PATH` (default: `./data/agent.db`)
- `TIMEZONE` (IANA timezone for display, e.g. `America/Vancouver`)
- `DISCORD_WEBHOOK_URL` (optional for v0; later we can switch to a bot)
- `AI_PROVIDER` (`auto`, `codex-oauth`, or `openai-api`; default: `auto`)
- `AI_MODEL` (optional model override)
- `OPENAI_API_KEY` (required when `AI_PROVIDER=openai-api`)
- `OPENAI_BASE_URL` (optional, default `https://api.openai.com/v1`)
- `SYLLABUS_LINK_KEYWORDS` (comma-separated keywords for syllabus link detection on front page/pages/files)

Example (`.env`):
```bash
CANVAS_BASE_URL=https://canvas.ubc.ca
CANVAS_ACCESS_TOKEN=...
DB_PATH=./data/agent.db
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

## Install (recommended)
Use `pipx` so you don’t have to manage venvs manually:

```bash
pipx install git+https://github.com/Liam-Frost/canvas-course-agent
```

Upgrade later:
```bash
pipx upgrade canvas-course-agent
```

## Dev quickstart
```bash
git clone https://github.com/Liam-Frost/canvas-course-agent
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

If you keep your `.env` elsewhere:
```bash
canvas-agent --env-path /path/to/.env init
```

## Basic usage
Helpful commands:
```bash
canvas-agent help
canvas-agent healthcheck
canvas-agent config show
canvas-agent config set filter.assignments on
```

1) Sync courses:
```bash
canvas-agent sync courses
```

2) List and star important courses:
```bash
canvas-agent courses list
canvas-agent courses list --term-like 2025W2

# by index
canvas-agent courses star 1 2 3

# by-code token matching (case-insensitive AND over course_code + name)
canvas-agent courses star --by-code CPEN 212

canvas-agent courses unstar 3
```

3) Sync items (defaults to ⭐ courses only):
```bash
canvas-agent sync assignments --days 14
canvas-agent sync quizzes --days 14
canvas-agent sync calendar --days 14

# disable noise filtering for a run
canvas-agent sync assignments --days 14 --no-filter
```

4) Show upcoming (merged view):
```bash
canvas-agent upcoming --days 14
```

5) Export:
```bash
# calendar file
canvas-agent export ics --days 30 --out ./export/canvas.ics

# course archive
canvas-agent export md --days 30 --out-dir ./export/md
```

6) Digest push (Discord)
```bash
# Print digest
canvas-agent digest --days 7

# AI-enhanced digest (adds one-line task descriptions)
canvas-agent digest --days 7 --ai-describe --ai-provider auto

# Weekly digest v2 (risk-prioritized) + AI action checklist
canvas-agent digest --days 14 --weekly-v2 --ai-describe --ai-weekly-plan --ai-provider auto

# Send digest to Discord webhook
canvas-agent digest --days 7 --send-discord
```

6) Telegram link + reminders:
```bash
# After sending /start to your bot
canvas-agent telegram link

# Preview reminders that would fire soon
canvas-agent remind run --lookahead-min 120

# Actually send
canvas-agent remind run --lookahead-min 2 --send-discord --send-telegram

# Custom reminders
canvas-agent remind add --title "Go to work" --at "2026-03-05 13:00" --channels discord
canvas-agent remind add --title "Stretch" --in 90m --channels telegram --silent
canvas-agent remind list
canvas-agent remind disable 1
```

7) AI adapter setup + probe (phase 1):
```bash
# Diagnose local auth/readiness first
canvas-agent ai doctor

# Project-local auth flow: codex oauth (device-auth; will prompt paste/code in terminal)
canvas-agent ai auth --provider codex-oauth

# Project-local auth flow: OpenAI API key (hidden prompt, writes .env)
canvas-agent ai auth --provider openai-api

# Auto mode (prefer OPENAI_API_KEY, fallback codex oauth)
canvas-agent ai probe --provider auto --prompt "Reply with OK"

# Force provider for debugging
canvas-agent ai probe --provider codex-oauth --prompt "Reply with OK"
canvas-agent ai probe --provider openai-api --model gpt-4.1-mini --prompt "Reply with OK"
```

8) AI-curated course dossiers (syllabus-centered):
```bash
# Ensure profile data has been synced first
canvas-agent profile sync --all

# Let AI pick likely syllabus source (front_page/page/pdf/syllabus_body),
# estimate grading composition, and curate dossiers
canvas-agent profile curate --all --provider auto --out-dir ./export/profiles_ai
```

9) Global academic state (AI):
```bash
# Generate cross-course term/week/exam-progress state snapshot
canvas-agent profile state --all --provider auto --out ./export/profiles_ai/global_state.md
```

10) First-run bootstrap (recommended):
```bash
# One command: sync profile data + AI dossier curation + global state + bootstrap meta
canvas-agent profile bootstrap --all --provider auto \
  --out-dir ./export/profiles_ai \
  --state-out ./export/profiles_ai/global_state.md \
  --meta-out ./export/profiles_ai/agent_bootstrap_state.json
```

11) Manual mapping override (when AI inference is wrong):
```bash
# List resolved AI mappings
canvas-agent ai map list --limit 30

# Force override for a specific task
canvas-agent ai map set --kind assignment --item-id 2380003 --course-id 178681 --topic "虚拟内存与页表"

# Clear override
canvas-agent ai map clear --kind assignment --item-id 2380003
```

Global toggles:
```bash
canvas-agent config set remind.enabled on
canvas-agent config set remind.discord.enabled on
canvas-agent config set remind.telegram.enabled on
```

## AI-first roadmap (next)
- Course-profile summarization and actionable weekly plans
- Risk-aware nudges (based on due density + missing/late trends)
- Prompt templates for per-course Q&A ("what should I do today?")
- Provider failover + retry tuning for AI adapters

## Scheduling
You have two options:
- Use your OS scheduler (recommended): see `deploy/` for templates (systemd/launchd/Windows Task Scheduler)
- Or just run `canvas-agent remind run ...` manually

### Linux (systemd timer)

Create a oneshot service + timer that runs every minute:

- Service: `/etc/systemd/system/canvas-agent-remind.service`
- Timer: `/etc/systemd/system/canvas-agent-remind.timer`

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now canvas-agent-remind.timer

# inspect
systemctl list-timers --all | grep canvas-agent-remind
journalctl -u canvas-agent-remind.service -n 50 --no-pager
```

Tip: to send only to Discord, set:
```bash
canvas-agent config set remind.telegram.enabled off
```

### Daily Canvas sync
Create a daily sync timer (00:00 server time):

- Service: `/etc/systemd/system/canvas-agent-sync.service`
- Timer: `/etc/systemd/system/canvas-agent-sync.timer`

### Digest push schedule
Templates are in `deploy/systemd/`:
- `canvas-agent-digest.service`
- `canvas-agent-digest-weekly.timer` (calendar-based)
- `canvas-agent-digest-every7d.timer` (every 7 days from activation)

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now canvas-agent-sync.timer

# inspect
systemctl list-timers --all | grep canvas-agent-sync
journalctl -u canvas-agent-sync.service -n 50 --no-pager
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
