# Running Cheez

The scheduled task is named **Cheez Daily** (claude.ai/code → Scheduled
tasks). How to create or change it: [SCHEDULING.md](SCHEDULING.md).

## What happens each weekday (default settings)

| London | New York | Step |
|---|---|---|
| 06:20 | 01:20 | The scheduled task starts a fresh cloud session on this repository. |
| 06:21 | | It installs Cheez, reads the private page to restore the ledger, archive and run log, and runs `cheez prepare`. |
| 06:22 | | Code fetches markets (US close, overnight futures, Asian close), the trading calendar, movers, earnings, stock facts, display FX rates and (if connected) the read-only Longbridge snapshot, and writes a research brief. |
| 06:25–06:55 | | The agent researches and writes the editorial and its translations (bounded: about 25 searches and 25 page fetches). |
| ~07:00 | 02:00 | `cheez check` validates it (up to 3 attempts), `cheez render` builds the page, it is published to the same private URL and, if enabled, emailed. You get a push notification when the run finishes. |
| 08:00 | 03:00 | European markets open. |
| 14:30 | 09:30 | US regular session opens (13:30 London in the weeks when US and UK clocks are out of step; the masthead says so). |

The delivery time and timezone are settings (CONFIGURATION.md). On NYSE
holidays the run publishes a short market-closed note instead. On early-close
days the masthead says so.

## Reading it

Open the private artifact link (pin it in claude.ai; it also appears in the
Claude app). The masthead shows the edition date, publication time, data
cut-off, session context and a status chip:

- **Complete**: all sources responded.
- **Partial data**: something was missing or stale; a banner lists what.
- **Market closed**: holiday note, no prices presented as fresh.
- A red **Not today's edition** banner appears if you open the page more than
  90 minutes after the next edition was due and none arrived.

The Archive section at the bottom opens any of the last 90 editions in place.
The Sources and method section lists each data source's status and the run
outcome.

## Manual refresh

- **From the claude.ai scheduled-task page** (claude.ai/code → Scheduled
  tasks → Cheez Daily → **Run now**). If today's edition already exists the run
  stops without publishing anything (idempotent).
- **For a revision** of today's edition (for example after the 08:30 New York
  data release, 13:30 London, or for fresher pre-market prices before the open), start a Claude Code session on this repository and say:
  "Produce a Cheez Daily revision for today using the cheez-edition skill,
  with `--force`, and publish to <your artifact URL>." The page then says
  "Revision 2".

## Pause, resume, change the time

On the scheduled-task page: the on/off switch pauses it; **Edit** changes the
prompt, schedule, environment or model. To move the delivery time, change
`[schedule]` in your settings and paste the cron line from `cheez schedule`.

## Check status

- The masthead chip and the run outcome in Sources and method.
- The scheduled task's run history (a run marked "succeeded" only means the
  session ended normally; the page's status chip is the authority).
- Locally: `cheez status` lists recent runs from `var/state/state.json`.

## Costs

- Each run uses your Claude subscription's usage, like an interactive session
  of roughly 20–40 minutes. There is no separate charge for the cloud
  environment. If you hit a usage limit, runs are rejected until it resets;
  the page will then show the "Not today's edition" banner.
- To reduce usage, edit the scheduled task to use a smaller model; quality of
  the writing and research will drop somewhat.
- No paid data services, servers or API keys are used.

## Where things live

| Thing | Location |
|---|---|
| Code, tests, skill, docs | This repository (public) |
| Editions, ledger, run log, archive | The private Cheez Daily artifact (and its version history) |
| Working files during a run | `var/` inside the cloud session (gitignored, deleted with the session) |
| Longbridge token | The cloud environment variable `CHEEZ_LONGBRIDGE_OAUTH` |
| Your settings | `cheez.toml` locally (gitignored); `CHEEZ_CONFIG_TOML` in the cloud environment |
| Email secret | `CHEEZ_SMTP_PASSWORD` / `CHEEZ_RESEND_API_KEY`, or a network secret for `api.resend.com` |

## Local development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[brokerage,dev]'
python -m pytest -q          # the full suite, no network needed
cheez demo                   # fictional demonstration edition → var/demo/site-demo/cheez-daily.html (+ email.html)
node scripts/screenshot.cjs var/demo/site-demo/cheez-daily.html screenshots/   # phone/laptop, light/dark
```

A manual live run in an interactive session:

```bash
cheez prepare --trigger manual        # facts + brief (var/editions/<id>/brief.md)
# write var/editions/<id>/editorial.json (see the skill)
cheez refresh                         # optional: re-fetch prices if research took long
cheez check && cheez render           # page → var/site/index.html
cheez email                           # optional: email preview → var/site/email.html (--send to deliver)
```

## Maintenance

- **Monthly-ish:** re-authorise Longbridge when the edition warns that the
  authorisation is expiring (SETUP.md step 2).
- **Each December:** update `exchange_calendars` (`pip install -U
  exchange_calendars`) so next year's holidays are known; China's calendar is
  published late, and Cheez labels Shanghai prices "unlabelled" until it is.
- **On a Longbridge SDK upgrade:** re-run the tests, re-check the
  allowlists in `src/cheez/brokerage/readonly.py` against the new SDK's method
  list, and re-read SECURITY.md's assumptions.
- **If a data source changes format:** that instrument shows as missing or
  stale and the edition is marked partial; fix the adapter in
  `src/cheez/sources/`.
