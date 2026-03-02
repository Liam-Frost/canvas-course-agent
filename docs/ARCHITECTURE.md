# Architecture (draft)

Event sources:
- Cron / scheduler (periodic sync + reminders)
- Discord messages (manual commands later)

Core pipeline:
1. Sync Canvas data (courses, syllabus, assignments, quizzes, calendar)
2. Normalize into local DB (SQLite)
3. Reminder engine emits notifications (Discord webhook/bot)
