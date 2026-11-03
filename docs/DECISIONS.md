# Decisions and assumptions

Recorded 3 November 2026. Each entry says what was decided, why, and what
would change it.

## Product and runtime

**A Claude Code scheduled task, plus a small Python package.** The deterministic
work (prices, calendars, the brokerage snapshot, portfolio arithmetic,
validation, rendering, the ledger) is ordinary tested Python in `src/cheez`.
The judgement work (choosing developments, research, writing, ideas) is done by
Claude in a cloud session following `.claude/skills/cheez-edition/SKILL.md`.
A scheduled task in Claude Code on the web starts a fresh cloud session each
weekday. This reuses the owner's Claude subscription instead of a separately
billed API key, needs no server, and runs while the owner's computer is off.
*Alternatives rejected:* a standalone app with its own scheduler (needs paid
hosting and an API key); GitHub Actions (this repository is public, so run
logs would be readable by anyone signed in to GitHub, and Actions cannot reach
claude.ai artifacts).

**One edition per US trading day, started at 07:41 New York time.** The cron is
`CRON_TZ=America/New_York 41 7 * * 1-5`, so daylight-saving changes in either
country never move it relative to the US open. A run takes roughly 20–40
minutes, so the edition is normally ready 60–90 minutes before the 09:30 open:
about 13:00–13:30 London, or 12:00–12:30 in the weeks when US and UK clocks
are out of step. The minute is deliberately off the hour (scheduled runs on
the hour can start late). Holidays, weekends and early closes come from the
`exchange_calendars` NYSE calendar; a closed-market day gets a short note with
no prices presented as a fresh session and no ideas. 08:30 New York data
releases (jobs, CPI) land after the edition and are shown as pending. A second
edition is not scheduled; a manual refresh produces a numbered revision.
*Would change if:* the owner wants a London-morning edition or a second
post-release edition (both are one scheduled task away).

**Holdings did not change the schedule.** No portfolio is connected yet. If
holdings turn out to be mostly Hong Kong or China shares, an Asia-close
edition would be worth adding; the snapshot already handles HKD positions,
labels Hong Kong closes and converts currencies explicitly.

## Publication and storage

**A private claude.ai artifact is the publication and the archive.** It reads
well on an iPhone and a laptop, is private by default, and keeps every publish
as a version. Because this repository is public, nothing private may be
committed, and a scheduled run's container is deleted afterwards. So the page
carries its own memory: the idea ledger, run log, edition index and the last
90 editions are embedded in it, and each run reads the page back before
writing the next edition. *Trade-off:* the archive inside the page is capped
at 90 editions (older ones remain in the artifact's version history).

**Stale editions announce themselves.** Each page stores when the next edition
is due; if the reader opens it more than 90 minutes after that, a red banner
says this is not today's edition. Failed runs publish a labelled
market-data-only edition rather than leaving yesterday's page up.

## Data

**Numbers come from code; the model never supplies a price.** Validation
rejects any idea whose levels are not near computed reference levels, and
computes reward ÷ risk itself.

**Sources.** Index, futures, FX and commodity levels come from Yahoo Finance's
public chart endpoint; earnings dates and large movers from Nasdaq.com and
Yahoo's screeners; official US yields from the US Treasury; ticker identities
from Nasdaq Trader's listed-securities directory. Each value is labelled with
its session (close, live, pre-market, futures) and timestamp, and changes are
measured against a named reference. *Caveat the owner must decide on:* the
Yahoo and Nasdaq terms of use prohibit automated collection. Cheez uses them
at very low volume for one private reader, but that is a risk to accept
explicitly or replace (see SETUP.md, "Data sources").

**Universe.** Featured stocks and ideas are limited to US-listed shares and
plain ETFs with at least about $5m of average daily trading. Leveraged and
inverse products are refused.

## Brokerage

**OAuth with read-only scopes, enforced three ways** (Longbridge's servers,
Cheez's client allowlist, and a Claude Code hook). Legacy API keys are refused
because they can trade and cannot be scoped. The SDK's browser login and the
official CLI's token store were both rejected after testing: the first lacks
PKCE in the current release and can hang; the second is encrypted to the
machine it ran on. Cheez therefore exchanges a Longbridge Agent Auth Code
itself and checks the granted scopes before saving anything. Details in
SECURITY.md.

**Refreshed tokens are not written back.** The scheduled run's container is
temporary and environment secrets are read-only to it. If Longbridge rotates
refresh tokens, the stored token stops working when the access token expires
(the documented example is 30 days), and Cheez will say "authorisation
expired" in the portfolio section. The edition warns seven days before expiry.

## Analysis rules

- Cash means cash: broker buying power includes margin and is never treated
  as spendable. Free cash is the broker's withdrawable cash, floored at zero.
- Currencies are never added without an explicit, timestamped FX rate, which
  is shown.
- Unrealised gain/loss is shown only against the broker's reported cost price
  and is labelled; realised P&L and performance are not calculated, because a
  partial API history cannot prove the full trade and deposit record.
- No position sizes. Feasibility notes show only how much free cash in the
  right currency exists, as an arithmetic ceiling. Sizing waits for risk
  preferences the owner has not configured.
- The model never sees cost basis, quantities or account values, so ideas are
  not anchored on recovering a purchase price.
- Published ideas are recorded once and never edited; changes are dated
  revisions. A "zone touch" is a later day's range overlapping the zone, not a
  fill.

## Assumptions

1. The reader holds a Longbridge account (Hong Kong/Singapore or US data
   centre) and reads in Europe/London.
2. The reporting currency for an account is the broker's own base currency.
3. The owner accepts that Anthropic processes the research brief, which
   includes a minimised portfolio view (tickers, weights, no values).
4. The scheduled task runs in a cloud environment whose network policy allows
   the data sources (the current Default environment does).
5. The first live edition (3 Nov 2026) was produced during the US session
   because the build finished then; scheduled editions are pre-market.
