# Scheduling

Cheez is produced by an AI coding agent that runs on a schedule in the cloud,
in a fresh session on this repository. Code does the deterministic work; the
agent does the research and writing. Two agents are supported.

| | Claude Code scheduled task | OpenAI Codex (or another agent) |
|---|---|---|
| Instructions | `.claude/skills/cheez-edition/SKILL.md` | `AGENTS.md`, which points to the same skill |
| Publishes to | A private claude.ai artifact (page + archive) | Email (and `var/site/index.html`) |
| Read-only guard hook | Yes (`.claude/hooks/guard.py`) | No: see the warning below |
| Recommended | Yes | For email-only use without the brokerage connection |

## 1. Choose the delivery time

```bash
cheez config init        # once; edit [schedule] in cheez.toml
cheez schedule           # or: cheez schedule --agent codex
```

`cheez schedule` prints the delivery time, the start time and the cron line,
then the exact prompt to paste into the scheduled task. The defaults:

```text
Deliver by:   07:00 Europe/London (weekdays 1-5)
Start run at: 06:20 Europe/London (40 minutes earlier)
Cron:         CRON_TZ=Europe/London 20 6 * * 1-5
```

The cloud run cannot see your local `cheez.toml`. Put the same settings in
the cloud environment as `CHEEZ_CONFIG_TOML` (or individual `CHEEZ_*`
variables, see CONFIGURATION.md).

## 2a. Claude Code

claude.ai/code → **Scheduled tasks** → **New**:

| Setting | Value |
|---|---|
| Name | Cheez Daily |
| Repository | `czlin7/cheez`, as the only repository, outside a Project (so the repository's hooks and deny rules load) |
| Schedule | the `Cron` line from `cheez schedule` |
| Session | A fresh session for each run |
| Environment | `Cheez` (SETUP.md step 2) once created; `Default` until then |
| Connectors | None |
| Notifications | Push on completion |
| Prompt | the prompt from `cheez schedule`, with your private artifact URL (or set `CHEEZ_ARTIFACT_URL` and it is filled in) |

The prompt, for reference:

```text
Produce today's Cheez Daily edition. This is an unattended scheduled run: do not ask questions.

1. In the repository root run: python3 -m venv .venv && .venv/bin/pip install -q -e '.[brokerage]'
   Afterwards call every Cheez command as .venv/bin/cheez.
2. Follow .claude/skills/cheez-edition/SKILL.md exactly (agents other than Claude Code: see AGENTS.md).
3. Never place, change or cancel orders; never commit, push or open a pull request.
4. If a step fails and cannot be fixed within the skill's retry budget, run `.venv/bin/cheez fail "<short reason>"`
   and still deliver what it produced.
5. Publish var/site/index.html to the private page <CHEEZ_ARTIFACT_URL> (Artifact tool, publish with that url). Never create a new
   artifact and never make it public.
6. Then run `.venv/bin/cheez email --send` to email the digest.      ← only when email is enabled
Finish with the three-line report described in the skill.
```

The first time, there is no page yet: start an interactive Claude Code session
on this repository, ask it to produce an edition with the skill and publish it
as a new private artifact, then put that URL in the task.

Press **Run now** once to check. A second run on the same day stops with
`duplicate` and publishes nothing, so retries are safe.

## 2b. OpenAI Codex (cloud tasks) or another agent

Any agent that can run shell commands in a checkout of this repository and
browse the web can produce an edition. It reads `AGENTS.md`, follows the same
skill, and skips the Claude-only publishing step; delivery is by email.

1. Connect the repository to the agent's cloud environment and allow outbound
   access to the data sources (Yahoo Finance, Nasdaq.com, US Treasury, Nasdaq
   Trader) and, for email, your SMTP server or `api.resend.com`.
2. Set `CHEEZ_CONFIG_TOML` (with `[email] enabled = true` and your address)
   and the email secret in the environment's settings.
3. Schedule the prompt from `cheez schedule --agent codex` at the printed time,
   using whatever scheduling the agent offers (or an external scheduler that
   starts a task).

> **Warning: no guard hook outside Claude Code.** The read-only brokerage
> boundary still holds at the credential (read-only OAuth scopes) and in
> Cheez's client allowlist, but the third layer, the hook that locks the agent
> down when a brokerage token is present, is Claude Code-specific. Do not give
> another agent the Longbridge token unless you accept that. Without the
> token, Cheez publishes everything except the portfolio section.

## Changing the time later

Edit `[schedule]` (and `CHEEZ_CONFIG_TOML` in the cloud environment), run
`cheez schedule`, and paste the new cron line into the task. The page's
"Not today's edition" banner uses the configured delivery time, so keep the
two in step.

## Pause and resume

On the scheduled-task page: the on/off switch pauses it; **Edit** changes
prompt, schedule, environment or model.
