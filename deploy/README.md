# Deployment

This folder contains **templates** for scheduling sync + reminders on different platforms.

## Common recommendation: pipx
Install the CLI in an isolated env:

```bash
pipx install git+https://github.com/Liam-Frost/canvas-course-agent
```

Then run:

```bash
canvas-agent --env-path /path/to/.env init
```

## Linux (systemd)
See `deploy/systemd/` for unit templates.

## macOS (launchd)
See `deploy/launchd/` for LaunchAgent templates.

## Windows (Task Scheduler)
See `deploy/windows/install-tasks.ps1`.
