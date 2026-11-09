"""The scheduled-run instructions for Claude Code or an OpenAI Codex agent,
generated from settings so the start time always matches the delivery time."""

from __future__ import annotations

from .settings import Settings

COMMON = """\
Produce today's Cheez Daily edition. This is an unattended scheduled run: do not ask questions.

1. In the repository root run: python3 -m venv .venv && .venv/bin/pip install -q -e '.[brokerage]'
   Afterwards call every Cheez command as .venv/bin/cheez.
2. Follow .claude/skills/cheez-edition/SKILL.md exactly (agents other than Claude Code: see AGENTS.md).
3. Never place, change or cancel orders; never commit, push or open a pull request.
4. If a step fails and cannot be fixed within the skill's retry budget, run `.venv/bin/cheez fail "<short reason>"`
   and still deliver what it produced.
"""

CLAUDE = COMMON + """\
5. Publish var/site/index.html to the private page {url} (Artifact tool, publish with that url). Never create a new
   artifact and never make it public.{email}
Finish with the three-line report described in the skill.
"""

CODEX = COMMON + """\
5. There is no Claude artifact in this run: delivery is by email{email_or_file}.
Finish with the three-line report described in the skill.
"""


def prompt(cfg: Settings, agent: str = "claude") -> str:
    email = "\n6. Then run `.venv/bin/cheez email --send` to email the digest." if cfg.email.enabled else ""
    if agent == "codex":
        how = " (`.venv/bin/cheez email --send`)" if cfg.email.enabled else \
            " — email is not enabled, so leave var/site/index.html as the output and say so"
        return CODEX.format(email_or_file=how)
    return CLAUDE.format(url=cfg.publish.artifact_url or "<CHEEZ_ARTIFACT_URL>", email=email)


def describe(cfg: Settings, agent: str = "claude") -> str:
    s = cfg.schedule
    start = s.start_time()
    return "\n".join([
        f"Deliver by:   {s.deliver_at} {s.timezone} (weekdays {s.weekdays})",
        f"Start run at: {start:%H:%M} {s.timezone} ({s.lead_minutes} minutes earlier)",
        f"Cron:         {s.cron()}",
        "",
        f"Prompt for the scheduled task ({agent}):",
        "-" * 60,
        prompt(cfg, agent),
    ])
