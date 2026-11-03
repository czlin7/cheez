# One-time setup

Cheez already publishes a market edition without any of this. These steps add
your Longbridge portfolio (read-only) and tidy up the schedule. Each takes a
few minutes.

## 1. Keep the scheduled task pointed at the code

The scheduled task checks out the branch `claude/cheez-daily-briefing-1ce5zf`.
If you merge that branch into `main` and delete it, edit the task's prompt
(claude.ai/code → Scheduled tasks → Cheez Daily → Edit) and remove the
`git fetch … && git checkout …` line, so it uses `main`.

Recommended: protect `main` on GitHub (Settings → Branches → add a rule
requiring pull-request review), so no automated session can change the code
that scheduled runs execute.

## 2. Connect Longbridge read-only (optional, for the portfolio section)

You need a computer with Python 3.11 or newer for steps a–c. The token never
passes through a chat.

a. Install Cheez on your computer:

```bash
pip install "cheez[brokerage] @ git+https://github.com/czlin7/cheez@claude/cheez-daily-briefing-1ce5zf"
```

b. Open <https://open.longbridge.com/connect> and create an Agent Auth Code.
   **Untick every permission except account access (assets, positions, cash
   flow) and, if you want open orders and trade history, order/trade lookup.**
   Longbridge ticks trading permissions by default: make sure placing orders,
   and watchlist editing, are unticked. If you have several Longbridge
   accounts, choose the one Cheez should read (one token per account).

c. Within five minutes, run:

```bash
cheez brokerage-authorize
```

   Paste the code at the hidden prompt. Cheez exchanges it, reads the scopes
   Longbridge actually granted, and **refuses to save the token** if it
   includes trading or watchlist permissions (then remove that authorisation
   in the Longbridge app's security settings and repeat with fewer boxes
   ticked). On success it writes `~/.cheez/longbridge-token.json`, readable
   only by you.

d. In claude.ai → Code, open the environment menu → **create a new
   environment** named `Cheez`, with the same network access as your Default
   environment. Add one environment variable:

   - Name: `CHEEZ_LONGBRIDGE_OAUTH`
   - Value: the single line inside `~/.cheez/longbridge-token.json`

   Use a dedicated environment so the token is not visible to sessions for
   your other projects. Any session with this variable is automatically locked
   down by Cheez's guard (it can only run `cheez` commands).

e. Edit the scheduled task and switch its environment to `Cheez`.

f. Optional check: start a session in the `Cheez` environment on this
   repository and ask it to run `cheez brokerage-check`. It prints the scopes
   and expiry, never account data.

Re-authorise (steps b–d) when the edition warns that the authorisation is
expiring, or if the portfolio section says it has expired. To revoke access at
any time, remove the authorisation in the Longbridge app's security settings
and delete the environment variable.

## 3. Decide on the public market-data feeds

Cheez's index, futures, FX and commodity levels and its stock screens come
from Yahoo Finance and Nasdaq.com public endpoints, whose terms of use do not
permit automated collection. Cheez uses them at very low volume for one
private reader and labels everything, but the choice is yours:

- **Accept** the risk for private use (current setting), or
- **Ask** for Cheez to be switched to official and broker sources only
  (US Treasury, ECB, Federal Reserve, Longbridge quotes once connected). The
  cross-asset table would become thinner (no live futures or non-US indices).

## 4. Make it easy to read

- Pin the Cheez Daily artifact in claude.ai (it then appears in your sidebar).
- Push notifications for the scheduled task are on; you get one when each run
  finishes.

## Environment variables reference

| Variable | Purpose |
|---|---|
| `CHEEZ_LONGBRIDGE_OAUTH` | Read-only Longbridge OAuth token (JSON from `cheez brokerage-authorize`). Its presence also switches on the agent lockdown. |
| `CHEEZ_LONGBRIDGE_SCOPES` | Only if a token was created another way and does not record its scopes: the scopes you granted, e.g. `account.read,trade.read`. Cheez fails closed without it. |
| `CHEEZ_LOCKDOWN=1` | Forces the agent lockdown even without a token. |
| `CHEEZ_HOME` | Overrides the private working directory (default `var/`). |

Never set `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET` or
`LONGBRIDGE_ACCESS_TOKEN` (or the `LONGPORT_` equivalents): those legacy
credentials can trade, and Cheez disables the brokerage connection if it sees
them.
