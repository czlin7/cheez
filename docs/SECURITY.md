# Security, privacy and the read-only boundary

Cheez reads a Longbridge account. It must never change it. This page explains
how that is enforced, what data goes where, and what risk remains.

## What Cheez can and cannot do

Cheez **can** read: total account value, cash by currency, holdings and
quantities, broker cost prices, open orders, filled trades and cash flows, and
market quotes.

Cheez **cannot** place, replace, cancel or schedule an order; move money;
change account settings; edit watchlists or broker alerts; or post anything to
Longbridge. These are blocked in three independent layers, none of which
relies on instructions to the language model.

## Layer 1: the credential itself (enforced by Longbridge)

Cheez accepts only an **OAuth 2.0** token, and only when it carries the
scopes `account.read` and, optionally, `trade.read`. The token is created once
with `cheez brokerage-authorize`, which exchanges a Longbridge Agent Auth Code
through the documented `POST /oauth2/token` call (the same exchange Longbridge's
CLI and MCP server use), reads the `scope` field Longbridge returns, and
**refuses to save the token** if it includes `trade.write` or `watchlist`.
This matters because Longbridge's consent page ticks every permission,
including trading, by default. (The official CLI's own login is not used: it
stores the token encrypted to the machine it ran on.)

- Without `trade.write`, Longbridge's servers reject order placement,
  replacement and cancellation (error `403308`), whatever the client sends.
  Source: <https://open.longbridge.com/docs/getting-started.md> (OAuth scopes).
- `watchlist` is refused because it includes write access.
- The legacy App Key / App Secret / Access Token is refused outright: it has no
  scopes, and Longbridge's documentation warns that anyone holding it "can
  trade your account". If any legacy variable is present in the environment,
  Cheez disables the brokerage connection entirely.
- Before every run, Cheez re-checks the scopes recorded with the token. If
  they cannot be established, Cheez **fails closed** (no brokerage
  connection) unless the owner has recorded the scopes they granted in
  `CHEEZ_LONGBRIDGE_SCOPES`. Run `cheez brokerage-check` to see the result.
- A `403308` error from Longbridge is not treated as proof that scopes work:
  Longbridge also uses it for markets an account cannot trade.
- Each token is bound to one Longbridge account. A second account needs its
  own token; Cheez reports accounts separately.

Residual risk at this layer: even a token with no scopes can create or delete
price alerts and sharelists and post community topics through Longbridge's
general APIs. Layers 2 and 3 exist for exactly that reason.

## Layer 2: the client (enforced by Cheez's code)

- The SDK (`longbridge==5.3.0`) is imported in one place only:
  `src/cheez/brokerage/longbridge.py`, inside a child process with a hard
  timeout. The child runs in an empty working directory with explicit API
  endpoints and no `LONGBRIDGE_*` variables, because the SDK otherwise reads
  a `.env` file and endpoint overrides that could redirect the token, and
  logs raw responses if a log path is set. Login uses the SDK's asynchronous
  builder under a 45-second timeout, so an expired authorisation fails
  cleanly instead of waiting for a browser.
- Every SDK object is wrapped in `ReadOnlyProxy`, which exposes an explicit
  allowlist of read methods (`src/cheez/brokerage/readonly.py`) and raises on
  anything else.
- The raw HTTP client is used only as a fallback for one known SDK parsing
  bug, wrapped in `SafeHttpGet`: GET only, fixed list of read paths.
- Contexts that can mutate anything (alerts, sharelists, community posts,
  recurring investments, grid and fund orders, AI conversations) are never
  constructed.
- `tests/test_readonly_boundary.py` scans every Python file for calls to
  mutating methods or unsafe clients, and runs the whole snapshot against a
  local mock server, asserting that **only GET requests** were sent.
- Safety is never tested by submitting a real order.

## Layer 3: the agent harness (enforced by Claude Code)

`.claude/settings.json` registers `.claude/hooks/guard.py` as a PreToolUse
hook. Claude Code runs it before every tool call; it is not part of the model.

- **Always**: blocks any tool input that would call a Longbridge mutating
  method or build an unsafe client.
- **Lockdown** (whenever a Longbridge credential is present in the
  environment) switches to an allowlist. The agent may run only the setup
  steps and `.venv/bin/cheez` with validated arguments: no `cd`, globs, `..`,
  pipes, redirection, variables or other programs. It may read only inside
  the repository and Claude's own working folders, and write only data files
  (json, md, txt, html) under `var/`. Both checks use resolved paths, so
  `/proc`, `/dev/fd` and symlink tricks do not work. It may not use
  connectors or contact the broker directly, and any tool call containing the
  credential is blocked. Even a model misled by a malicious web page cannot
  write and run its own code, read the token, or change the guard.
- The hook is registered as `python3 guard.py || exit 2`, so if the guard is
  missing or crashes, the call is blocked rather than allowed.
- An independent adversarial review on 3 Nov 2026 found and reproduced
  bypasses in an earlier, denylist-style version (glob and `/dev/fd` reads of
  the environment, `var/../` path traversal, module shadowing). All are fixed
  and each one is now a regression test in `tests/test_readonly_boundary.py`.

Repository settings and hooks apply to cloud sessions that use a single
repository outside a Project, which is how the scheduled task is configured.
Verified on 3 Nov 2026: in a headless Claude Code session started from this
repository with lockdown on, the hook refused `printenv` before it ran
("Cheez guard: that program or path is not allowed").

### Pending guard update

The lockdown allowlist in `.claude/hooks/guard.py` was written before
`cheez email`, `cheez config` and `cheez schedule` existed, so in the locked
environment (Longbridge token present) those commands are refused. The
intended addition, for the owner to review and apply by hand (automated
sessions are rightly not allowed to edit their own guard):

```python
# in _cheez_args_ok(), before the final `return False`
if sub == "config":
    return rest in ([], ["show"], ["path"])          # never `init`
if sub == "schedule":
    return rest in ([], ["--agent", "claude"], ["--agent", "codex"])
if sub == "email":
    return len(rest) == len(set(rest)) and all(a in ("--send", "--force") for a in rest)
```

Recipients come only from settings and the environment, which the locked
agent cannot change, so allowing `email --send` does not let the agent send
the edition anywhere else. Add matching cases to
`tests/test_readonly_boundary.py`. Without a token (no lockdown) all commands
already work.

## Where data goes

| Data | Where it goes | Why |
|---|---|---|
| Longbridge token | Cloud environment secret → the Cheez child process → Longbridge only | Read the account |
| Holdings and cash (sanitised: no account numbers; broker order and trade ids hashed) | Private working files under `var/` in the cloud session; the private artifact page | Build the report |
| Minimised portfolio view (tickers, weights, whether cash/sellable quantity exists; **no** cost basis, quantities or values) | The language model (Anthropic), via the research brief | Relate ideas to existing exposure |
| Company names and topics | Web search providers | Research. Holdings are never searched as "my portfolio"; quantities and values are never searched |
| Market data requests (tickers, including holdings) | Yahoo Finance, Nasdaq.com, US Treasury | Prices and calendars |
| The email digest (no portfolio unless `include_portfolio`) | Your SMTP server or Resend, then your mailbox | Inbox delivery, only when enabled |

**Model-provider data flow.** The scheduled run is a Claude Code session, so
everything the agent reads (the brief, search results, the editorial) is
processed by Anthropic's models under your Claude plan's terms. Cheez keeps
the portfolio part of that small and leaves out cost basis and account
identifiers.

## Privacy of output

- The repository `czlin7/cheez` is **public**. Nothing private is ever
  committed: all output, caches and state live under `var/`, which is
  gitignored. `cheez` never runs git commands.
- Editions are published to a **private** claude.ai artifact (visible only to
  you unless you share it). Its history is kept as artifact versions; the
  ledger, run log and recent archive are embedded in the page itself.
- Nothing is emailed unless you turn email on (EMAIL.md); the digest then
  leaves out the portfolio by default. No connectors are attached to the
  scheduled task.
- Settings that contain your email address live in `cheez.toml`
  (gitignored) or the cloud environment, never in the repository.

## If something leaks

1. Remove the authorisation in the Longbridge app (security settings), which
   stops renewal. Tokens already issued stay valid until they expire.
2. Delete `CHEEZ_LONGBRIDGE_OAUTH` from the cloud environment.
3. Re-authorise with read-only scopes when ready (see SETUP.md).
