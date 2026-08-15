# Codex project guidance

## Role

- This is the production media-hosting and scheduled Instagram publishing repository for `@ur.money.kr`.
- `money-cardnews` prepares media and plan files; this repository exposes public media URLs and publishes from `plans/YYYY-MM-DD.json`.
- Treat timestamped media directories, `plans/`, and `done/` as production records. Never delete or rewrite them without an exact user-approved target.

## Safety

- Publishing, workflow dispatch, secret changes, notifications, and pushes are external side effects. Require an explicit request for the exact run.
- Preserve idempotency: check the plan, the `done/YYYY-MM-DD` marker, and recent-caption duplicate detection before retrying.
- Never bypass the five-minute spacing, activity-limit backoff, or duplicate checks.
- Never print, copy, or commit `IG_ACCESS_TOKEN`, `IG_USER_ID`, `GMAIL_APP_PASSWORD`, or `DISCORD_WEBHOOK` values.
- Default manual workflow dispatches to `dry_run=true`; changing to a live run requires explicit approval.

## Verification

- For publisher changes, run `python3 scripts/publish_from_plan.py --selftest` and `python3 -m py_compile scripts/*.py`.
- Validate YAML structure after workflow edits and review schedule/timezone consequences in KST.
- Do not call Instagram, email, Discord, or GitHub production APIs merely to test syntax.
- Changes to schedules, concurrency, permissions, retries, or `POST_HOUR` require an explicit operational review.

## Git and automation

- Prefer a separate branch/worktree for automated code changes.
- Keep media/plan uploads separate from workflow-code changes when practical.
- A successful publish can precede a failed `done` marker push; investigate external state before retrying.

