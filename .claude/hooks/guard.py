#!/usr/bin/env python3
"""Cheez PreToolUse guard (standard library only).

Claude Code runs this before every tool call in this repository. It enforces
the read-only brokerage boundary at the harness level, outside the model:

* Always: block any tool input that would call a Longbridge mutating method,
  construct a raw/unsafe SDK client, or reach the broker API directly.
* Lockdown (a Longbridge credential is present in the environment, i.e. the
  scheduled Cheez environment): the agent may only run `cheez` commands and a
  few read-only shell utilities, may only write inside var/, may not read the
  credential or process environment, and may not send the credential anywhere.

Exit code 2 blocks the call and shows the reason to the model. Any internal
error in lockdown blocks the call (fail closed).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

TOKEN_ENV = "CHEEZ_LONGBRIDGE_OAUTH"
LEGACY_ENV = ("LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN",
              "LONGPORT_APP_KEY", "LONGPORT_APP_SECRET", "LONGPORT_ACCESS_TOKEN")

MUTATING = re.compile(
    r"\.\s*(submit_order|submit_multileg|replace_order|cancel_order|create_watchlist_group|update_watchlist_group|"
    r"delete_watchlist_group|update_pinned|refresh_access_token(?:_async)?|create_topic(?:_reply)?|set_reminder|"
    r"continue_conversation|conversation)\s*\(|"
    r"\b(AlertContext|SharelistContext|DCAContext|GridContext|FundContext|AgentContext|ContentContext)\s*\(|"
    r"\bHttpClient\s*\.\s*from_",
    re.I,
)
# Direct broker endpoints: only the cheez package talks to Longbridge, never the agent.
BROKER_DIRECT = re.compile(
    r"\b(openapi|openapi-trade|openapi-quote|mcp)\.(longbridge|longportapp|longport|longbridgeapp)\.(com|cn)\b|"
    r"/v1/trade/order|/v1/watchlist|/v1/alert|/v1/asset/|/oauth2/",
    re.I,
)

SHELL_META = re.compile(r"[`<>;|]|\$\(|\$\{|\$[A-Za-z_]|&(?!&)")
BASH_FORBIDDEN_WORDS = re.compile(
    r"\b(env|printenv|export|set|declare|eval|exec|source\s+/proc|curl|wget|nc|ncat|socat|ssh|scp|node|deno|bun|"
    r"perl|ruby|php|osascript|base64|xxd|openssl|python[0-9.]*\s+-c|python[0-9.]*\s+-(?!m\s)|bash\s+-c|sh\s+-c|zsh\s+-c)\b|"
    r"/proc/|/run/|\.longbridge|\.ssh|\.credentials|\.ccr|\.netrc|\.git-credentials|\.config/gh",
    re.I,
)
ALLOWED_COMMANDS = [
    re.compile(r"^(\./)?(\.venv/bin/)?cheez(\s+[\w@:/.,=+'\" -]*)?$"),
    re.compile(r"^(\.venv/bin/)?python[0-9.]*\s+-m\s+cheez(\s+[\w@:/.,=+'\" -]*)?$"),
    re.compile(r"^(uv\s+)?pip[0-9.]*\s+install\s+(-q\s+)?(-e\s+)?['\"]?\.(\[brokerage\])?['\"]?(\s+-q)?$"),
    re.compile(r"^(\.venv/bin/)?python[0-9.]*\s+-m\s+pip\s+install\s+(-q\s+)?(-e\s+)?['\"]?\.(\[brokerage\])?['\"]?(\s+-q)?$"),
    re.compile(r"^(uv\s+venv|python[0-9.]*\s+-m\s+venv)\s+\.venv(\s+-q)?$"),
    re.compile(r"^(\.|source)\s+\.venv/bin/activate$"),
    re.compile(r"^cd\s+[\w/.~-]+$"),
    re.compile(r"^git\s+(status|log|rev-parse|branch|diff)(\s+[\w/.:@^~-]*)*$"),
    re.compile(r"^git\s+(fetch|checkout|switch|pull)\s+(origin\s+)?[\w/.-]+(\s+[\w/.-]+)?$"),
    # No `find` (its -exec runs programs) and no test runners: use the Glob and Grep tools instead.
    re.compile(r"^(ls|pwd|date|wc|head|tail|cat|grep|stat|du|df|nproc|true)(\s+[\w/.:*=,+@%-]+)*$"),
    re.compile(r"^mkdir\s+-p\s+var/[\w/.-]+$"),
    re.compile(r"^cp\s+[\w/.@-]+\s+var/[\w/.-]+$"),
]


def _repo() -> str:
    return os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _secrets(env: dict) -> list[str]:
    raw = env.get(TOKEN_ENV) or ""
    out = []
    try:
        tok = json.loads(raw)
        for k in ("access_token", "refresh_token"):
            v = str(tok.get(k) or "")
            if len(v) >= 12:
                out.append(v)
    except Exception:
        if len(raw) >= 12:
            out.append(raw)
    for k in LEGACY_ENV:
        v = env.get(k) or ""
        if len(v) >= 12:
            out.append(v)
    return out


def lockdown(env: dict) -> bool:
    return bool(env.get(TOKEN_ENV) or env.get("CHEEZ_LOCKDOWN") == "1" or any(env.get(k) for k in LEGACY_ENV))


def _contains_secret(blob: str, secrets: list[str]) -> bool:
    for s in secrets:
        for i in range(0, max(1, len(s) - 15), 8):
            if s[i:i + 16] and s[i:i + 16] in blob:
                return True
    return False


def _bash_ok(cmd: str) -> tuple[bool, str]:
    cmd = cmd.strip()
    if "\n" in cmd:
        return False, "multi-line shell commands are not allowed in the Cheez scheduled environment"
    if SHELL_META.search(cmd.replace("&&", " ").replace("2>&1", "")):
        return False, "shell redirection, pipes, substitution and variables are not allowed here"
    if BASH_FORBIDDEN_WORDS.search(cmd):
        return False, "that program or path is not allowed in the Cheez scheduled environment"
    for part in [p.strip() for p in cmd.replace("2>&1", "").split("&&")]:
        if not part:
            continue
        try:
            shlex.split(part)
        except ValueError:
            return False, "unparseable command"
        if not any(rx.match(part) for rx in ALLOWED_COMMANDS):
            return False, f"only `cheez` commands and read-only utilities may run here (blocked: {part[:80]!r})"
    return True, ""


def _path_ok_for_write(path: str) -> bool:
    repo = _repo()
    p = os.path.realpath(path if os.path.isabs(path) else os.path.join(repo, path))
    var = os.path.join(repo, "var") + os.sep
    home = os.environ.get("CHEEZ_HOME")
    allowed = [var] + ([os.path.realpath(home) + os.sep] if home else [])
    scratch = os.environ.get("CLAUDE_SCRATCHPAD_DIR")
    if scratch:
        allowed.append(os.path.realpath(scratch) + os.sep)
    if not any(p.startswith(a) for a in allowed):
        return False
    return os.path.splitext(p)[1].lower() in (".json", ".md", ".txt", ".html")


def decide(tool: str, tool_input: dict, env: dict) -> tuple[bool, str]:
    blob = json.dumps(tool_input, ensure_ascii=False)
    if MUTATING.search(blob):
        return False, ("Cheez is read-only: this would call a Longbridge mutating method, an unsafe client or the "
                       "broker API directly. Use the `cheez` commands, which only read.")
    if not lockdown(env):
        return True, ""
    if BROKER_DIRECT.search(blob):
        return False, "the agent may not contact the broker directly; `cheez prepare` reads the account"
    secrets = _secrets(env)
    if secrets and _contains_secret(blob, secrets):
        return False, "the brokerage credential must never appear in a tool call"
    if tool == "Bash":
        return _bash_ok(str(tool_input.get("command", "")))
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if not _path_ok_for_write(path):
            return False, "in the Cheez scheduled environment, files may only be written under var/ (json, md, txt, html)"
        return True, ""
    if tool == "Read":
        path = str(tool_input.get("file_path", ""))
        if re.search(r"(^|/)(proc|run|\.longbridge|\.ssh|\.ccr)(/|$)|\.env($|\.)|credentials|\.netrc", path):
            return False, "reading process environment or credential files is not allowed"
        return True, ""
    if tool in ("Grep", "Glob"):
        path = str(tool_input.get("path", ""))
        if re.search(r"(^|/)(proc|\.longbridge)(/|$)", path):
            return False, "searching process or credential paths is not allowed"
        return True, ""
    if tool.startswith("mcp__"):
        # No connectors are needed for an edition; Artifact publishing is a built-in tool.
        return False, "connectors are disabled in the Cheez scheduled environment"
    return True, ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    env = dict(os.environ)
    try:
        ok, reason = decide(str(payload.get("tool_name", "")), payload.get("tool_input") or {}, env)
    except Exception as e:  # fail closed only where it matters
        ok, reason = (not lockdown(env)), f"guard error: {type(e).__name__}"
    if ok:
        return 0
    sys.stderr.write(f"Cheez guard: {reason}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
