# Cheez — notes for Claude sessions

Cheez Daily is a private, read-only market briefing. Code computes every
number; Claude researches and writes; a validator decides what is publishable.

- **This repository is public.** Never commit editions, portfolio data, tokens
  or anything under `var/` (gitignored). `cheez` never runs git.
- **Read-only brokerage is a hard rule.** Never call Longbridge mutating
  methods, never construct raw SDK clients outside `src/cheez/brokerage/`,
  never test safety by placing an order. `.claude/hooks/guard.py` enforces
  this and locks the agent down whenever a Longbridge credential is present.
- To produce or repair an edition, follow `.claude/skills/cheez-edition/SKILL.md`.
- Run `python -m pytest -q` before committing; `cheez demo` builds a labelled,
  fully fictional demonstration edition under `var/demo/`.
- Design and decisions: `docs/DECISIONS.md`; security model: `docs/SECURITY.md`;
  operations: `docs/OPERATIONS.md`; one-time setup: `docs/SETUP.md`.
