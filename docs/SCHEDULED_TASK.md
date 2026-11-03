# The scheduled task

This is the exact configuration of the Claude Code scheduled task that
produces Cheez Daily. The artifact URL is private to you and is kept in the
task itself, not in this public repository.

| Setting | Value |
|---|---|
| Name | Cheez Daily |
| Repository | `czlin7/cheez` (single repository, not inside a Project, so the repo's hooks and deny rules apply) |
| Schedule | `CRON_TZ=America/New_York 41 7 * * 1-5` (07:41 New York, weekdays) |
| Session | A fresh session for each run |
| Environment | `Cheez` once created (SETUP.md step 2); `Default` until then |
| Connectors | None stored on the task. The repository also denies the Gmail, Drive, Calendar and Sheets connector tools. |
| Notifications | Push on completion |
| Model | Your account default; change in the task editor to trade quality for usage |

## Prompt

Replace `<CHEEZ_ARTIFACT_URL>` with the private page's URL.

```text
Produce today's Cheez Daily edition. This is an unattended scheduled run: do not ask questions.

1. In the repository root run:
   git fetch origin claude/cheez-daily-briefing-1ce5zf && git checkout claude/cheez-daily-briefing-1ce5zf
   (skip this step if that branch no longer exists; then use main)
2. Run: python3 -m venv .venv && . .venv/bin/activate && pip install -q -e '.[brokerage]'
   Afterwards call every Cheez command as .venv/bin/cheez (shell state does not persist between commands).
3. Follow .claude/skills/cheez-edition/SKILL.md exactly, with:
   - private page URL: <CHEEZ_ARTIFACT_URL>
   - trigger: scheduled (use `.venv/bin/cheez prepare --trigger scheduled --state-from <saved page path>`)
4. Publish only to that URL. Never create a new artifact, never make it public, never commit, push or open a pull request.
5. If a step fails and cannot be fixed within the skill's retry budget, run `.venv/bin/cheez fail "<short reason>"`, publish the result to the same URL, and report.
Finish with the three-line report described in the skill.
```

## Current state and activation

The task **exists but is paused**. It was created on 3 Nov 2026, but two things
prevent it from running:

- the code could not be pushed to GitHub (the Claude GitHub App has no write
  access to `czlin7/cheez`), and
- the tool that created it cannot attach a repository, and the repository
  must be attached so that Cheez's hooks load at session start.

To activate it:

1. Fix GitHub access at <https://claude.ai/connect-github> (install the Claude
   GitHub App on `czlin7/cheez`, or reconnect GitHub), then push the branch
   `claude/cheez-daily-briefing-1ce5zf` (ask any Claude Code session on this
   repository to push it, or push the git bundle from the build session).
2. claude.ai/code → Scheduled tasks → **Cheez Daily** → Edit → add the
   repository `czlin7/cheez` (as its only repository, outside a Project).
   Check the schedule reads `CRON_TZ=America/New_York 41 7 * * 1-5`.
3. Switch the task on.
4. Press **Run now** once. If today's edition already exists, the run should
   restore the page's state, report `duplicate` and stop; otherwise it
   publishes a full edition. Open the run's transcript and the page to
   confirm.
