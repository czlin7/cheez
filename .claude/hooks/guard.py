#!/usr/bin/env python3
"""Cheez PreToolUse guard (standard library only).

Claude Code runs this before every tool call in this repository. It enforces
the read-only brokerage boundary at the harness level, outside the model.

* Always: block Python that would call a Longbridge mutating method or build a
  raw SDK client (Bash commands that run Python, and source files under src/).
* Lockdown (a Longbridge credential is present in the environment, i.e. the
  scheduled Cheez environment): an allowlist, not a denylist.
  - Bash: only a fixed set of command shapes: the setup steps, `.venv/bin/cheez`
    with validated arguments, and a few harmless git/status commands. No cd,
    globs, '..', redirection, pipes, variables or substitutions.
  - Read/Grep/Glob: only inside the repository and Claude's own scratch and
    tool-result folders, checked on resolved paths (so /proc, /dev/fd, temporary
    copies and symlink tricks are out of reach).
  - Write/Edit: only data files (json, md, txt, html) inside var/ or the scratch
    folder, checked on resolved paths.
  - No connectors; no tool call may contain the credential; the agent may not
    contact the broker directly.

The hook is registered as `python3 guard.py || exit 2`, so if this file is
missing or crashes, the tool call is blocked (fail closed).
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
BRANCH = "claude/cheez-daily-briefing-1ce5zf"

MUTATING = re.compile(
    r"\.\s*(submit_order|submit_multileg|replace_order|cancel_order|create_watchlist_group|update_watchlist_group|"
    r"delete_watchlist_group|update_pinned|refresh_access_token(?:_async)?|create_topic(?:_reply)?|set_reminder|"
    r"continue_conversation)\s*\(|"
    r"\b(AlertContext|SharelistContext|DCAContext|GridContext|FundContext|AgentContext|ContentContext)\s*\(|"
    r"\bHttpClient\s*\.\s*from_",
)
BROKER_DIRECT = re.compile(
    r"\b(openapi|openapi-trade|openapi-quote|mcp)\.(longbridge|longportapp|longport|longbridgeapp)\.(com|cn)\b|"
    r"/v1/trade/order|/v1/watchlist|/v1/alert|/v1/asset/|/oauth2/",
    re.I,
)
ARG_META = re.compile(r"[`<>;|*?\[\]{}~\\$]|\.\.")
DATA_EXT = (".json", ".md", ".txt", ".html")
TICKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,11}$")
EXACT = {
    ("git", "fetch", "origin", BRANCH), ("git", "checkout", BRANCH), ("git", "status"),
    ("git", "rev-parse", "HEAD"), ("git", "log", "--oneline", "-5"),
    ("python3", "-m", "venv", ".venv"), ("pwd",), ("date",), ("date", "-u"), ("true",),
    (".venv/bin/pip", "install", "-q", "-e", ".[brokerage]"),
    (".venv/bin/pip", "install", "-e", ".[brokerage]", "-q"),
    (".venv/bin/pip", "install", "-q", "-e", "."),
}


def _repo() -> str:
    return os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _roots(write: bool) -> list[str]:
    roots = [os.path.join(_repo(), "var") if write else _repo(), "/tmp/claude-0"]
    if not write:
        roots.append(os.path.join(os.path.expanduser("~"), ".claude", "projects"))
    for k in ("CLAUDE_SCRATCHPAD_DIR", "CHEEZ_HOME"):
        if os.environ.get(k):
            roots.append(os.environ[k])
    return [os.path.realpath(r) + os.sep for r in roots]


def _resolve(path: str) -> str:
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(_repo(), path))


def _inside(path: str, roots: list[str]) -> bool:
    p = _resolve(path) + os.sep
    return any(p.startswith(r) for r in roots)


def _secrets(env: dict) -> list[str]:
    raw = env.get(TOKEN_ENV) or ""
    out: list[str] = []
    try:
        tok = json.loads(raw)
        if isinstance(tok, dict):
            out = [str(tok.get(k) or "") for k in ("access_token", "refresh_token")]
    except Exception:
        out = [raw]
    out += [env.get(k) or "" for k in LEGACY_ENV]
    return [s for s in out if len(s) >= 12]


def lockdown(env: dict) -> bool:
    return bool(env.get(TOKEN_ENV) or env.get("CHEEZ_LOCKDOWN") == "1" or any(env.get(k) for k in LEGACY_ENV))


def _contains_secret(blob: str, secrets: list[str]) -> bool:
    for s in secrets:
        for i in range(0, max(1, len(s) - 11), 4):
            if s[i:i + 12] in blob:
                return True
    return False


# ------------------------------------------------------------- Bash allowlist

def _cheez_args_ok(args: list[str]) -> bool:
    if not args:
        return False
    sub, rest = args[0], args[1:]
    if sub in ("status", "refresh", "check"):
        return rest == [] or (len(rest) == 2 and rest[0] == "--edition" and bool(re.match(r"^\d{4}-\d{2}-\d{2}-us$", rest[1])))
    if sub == "add-stocks":
        return 0 < len(rest) <= 20 and all(TICKER.match(t) for t in rest)
    if sub == "prepare":
        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "--force":
                i += 1
            elif a == "--trigger" and i + 1 < len(rest) and rest[i + 1] in ("scheduled", "manual", "test"):
                i += 2
            elif a == "--state-from" and i + 1 < len(rest):
                p = rest[i + 1]
                if ARG_META.search(p) or not p.endswith(".html") or not _inside(p, _roots(False)) \
                        or not os.path.isfile(_resolve(p)):
                    return False
                i += 2
            else:
                return False
        return True
    if sub == "render":
        return rest in ([], ["--closed"]) or (len(rest) == 2 and rest[0] == "--market-only")
    if sub == "fail":
        return len(rest) == 1
    return False


def _bash_ok(cmd: str) -> tuple[bool, str]:
    cmd = cmd.strip()
    if "\n" in cmd or "\r" in cmd:
        return False, "multi-line shell commands are not allowed in the Cheez scheduled environment"
    body = cmd.replace(" 2>&1", "")
    for part in [p.strip() for p in body.split("&&")]:
        if not part:
            continue
        # Shell operators are refused outside quotes; free text is allowed only as the reason argument.
        try:
            lex = shlex.shlex(part, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            tokens = list(lex)
            argv = shlex.split(part)
        except ValueError:
            return False, "unparseable command"
        if any(t in ("|", "||", ";", "&", "<", ">", ">>", "(", ")") for t in tokens) or "`" in part or "$" in part:
            return False, "pipes, redirection, variables and substitutions are not allowed here"
        if tuple(argv) in EXACT:  # fixed strings, safe as written
            continue
        free = len(argv) >= 2 and argv[0].endswith(".venv/bin/cheez") and (
            argv[1] == "fail" or (len(argv) >= 3 and argv[-2] == "--market-only"))
        for a in (argv[:-1] if free else argv):
            if ARG_META.search(a):
                return False, "globs, '..', redirection, pipes, variables and substitutions are not allowed here"
        if tuple(argv) in EXACT:
            continue
        if argv and argv[0] in (".venv/bin/cheez", "./.venv/bin/cheez") and _cheez_args_ok(argv[1:]):
            continue
        return False, ("in the Cheez scheduled environment only the setup steps and `.venv/bin/cheez` commands "
                       f"may run (blocked: {part[:80]!r})")
    return True, ""


# ------------------------------------------------------------------ decision

def decide(tool: str, tool_input: dict, env: dict) -> tuple[bool, str]:
    blob = json.dumps(tool_input, ensure_ascii=False)
    if not lockdown(env):
        # Development: only stop code that would actually call a mutating SDK method.
        if tool == "Bash" and "python" in str(tool_input.get("command", "")) and MUTATING.search(blob):
            return False, "Cheez is read-only: this would call a Longbridge mutating method or build a raw SDK client."
        if tool in ("Write", "Edit", "MultiEdit"):
            path = str(tool_input.get("file_path") or "")
            rel = os.path.relpath(_resolve(path), _repo()) if path else ""
            if rel.startswith("src" + os.sep) and MUTATING.search(blob):
                return False, "Cheez source code may not call Longbridge mutating methods or build raw SDK clients."
        return True, ""

    if MUTATING.search(blob) or BROKER_DIRECT.search(blob):
        return False, "the agent may not contact the broker directly; `cheez prepare` reads the account read-only"
    secrets = _secrets(env)
    if secrets and _contains_secret(blob, secrets):
        return False, "the brokerage credential must never appear in a tool call"
    if tool == "Bash":
        return _bash_ok(str(tool_input.get("command", "")))
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if not path or ".." in path or not _inside(path, _roots(True)) or not _resolve(path).lower().endswith(DATA_EXT):
            return False, "in the Cheez scheduled environment, only data files (json, md, txt, html) under var/ may be written"
        return True, ""
    if tool == "Read":
        path = str(tool_input.get("file_path", ""))
        if not path or not _inside(path, _roots(False)):
            return False, "reading outside the repository and Claude's own working folders is not allowed here"
        return True, ""
    if tool in ("Grep", "Glob"):
        path = str(tool_input.get("path") or _repo())
        pattern = str(tool_input.get("glob") or "") + (str(tool_input.get("pattern") or "") if tool == "Glob" else "")
        if ".." in pattern or pattern.startswith("/") or not _inside(path, _roots(False)):
            return False, "searching outside the repository is not allowed here"
        return True, ""
    if tool.startswith("mcp__"):
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
    except Exception as e:
        ok, reason = (not lockdown(env)), f"guard error: {type(e).__name__}"
    if ok:
        return 0
    sys.stderr.write(f"Cheez guard: {reason}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
