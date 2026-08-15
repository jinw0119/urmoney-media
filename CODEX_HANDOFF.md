# Codex handoff: urmoney-media

## Identity

- Product/account: 얼마니, `@ur.money.kr`
- Local repository: `/Users/macbookpro/Claude/urmoney-media`
- Remote: `git@github.com:jinw0119/urmoney-media.git`
- Default branch: `main`
- Migration baseline: `6de340d`
- Producer repository: `/Users/macbookpro/Claude/money-cardnews`

At migration time, `main` matched `origin/main` and the working tree was clean.

## Production responsibilities

- Host timestamped public media files for the Instagram Content Publishing API.
- Store daily publication plans under `plans/`.
- Publish with `.github/workflows/publish.yml` and `scripts/publish_from_plan.py`.
- Monitor missing plans with `.github/workflows/watchdog.yml` and `scripts/watchdog.py`.
- Record completed runs under `done/YYYY-MM-DD`.

## Critical invariants

- `publish.yml` runs every 30 minutes because GitHub scheduled triggers can be late or missed.
- `POST_HOUR` and optional plan-level `post_hour` determine the KST publication window.
- A `done` marker and recent-caption lookup prevent duplicate publication.
- Items are separated by five minutes; activity-limit retries back off before retrying.
- Publishing may succeed even when a later API response or marker push fails. Always inspect external state before replaying.

## Secrets

GitHub Actions uses `IG_ACCESS_TOKEN`, `IG_USER_ID`, `GMAIL_APP_PASSWORD`, and `DISCORD_WEBHOOK`. Values belong in GitHub Secrets and must not be copied into repository files or task prompts.

## Verification

- `python3 scripts/publish_from_plan.py --selftest`
- `python3 -m py_compile scripts/*.py`
- Review workflow YAML, permissions, concurrency, timeout, schedule, and KST conversion.
- Use `workflow_dispatch` with `dry_run=true` for an explicitly requested credential/plan validation.

## Automation posture

Codex scheduled checks should initially be read-only: inspect workflow failures, missing plans, stale `done` markers, and recent commits. Production dispatch, retries, schedule edits, secret changes, and repository pushes remain approval-gated.

