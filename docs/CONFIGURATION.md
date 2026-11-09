# Configuration

Cheez works with no configuration at all. Settings change when the brief
arrives, which languages are written, whether prices are also shown in a
second currency, and whether a digest is emailed.

## Where settings live

Later layers win:

1. Built-in defaults.
2. A TOML file: `$CHEEZ_CONFIG` if set, otherwise `cheez.toml` in the
   repository root (gitignored), otherwise `~/.config/cheez/cheez.toml`.
   `cheez config init` writes a commented starter file.
3. `$CHEEZ_CONFIG_TOML`: the whole TOML as one environment variable. Use this
   in a Claude Code cloud environment, where a scheduled run starts from a
   fresh clone and cannot see a local file.
4. Single-value environment variables (table below).

`cheez config` prints the settings in effect and which layers they came from
(recipient addresses are counted, not printed). This repository is public, so
never commit a `cheez.toml` that contains your email address.

## Settings

```toml
[schedule]
deliver_at = "07:00"           # when the brief should be ready, in your timezone
timezone = "Europe/London"     # IANA name; every time in the report is shown in it
lead_minutes = 40              # a run takes about this long; the task starts this much earlier
weekdays = "1-5"               # cron day-of-week (Mon–Fri)

[report]
languages = ["en", "zh-Hant", "zh-Hans"]   # languages written each day (English always)
default_language = "en"        # what the page shows first: en | zh-Hant | zh-Hans
convert_to = ""                # "" = off; or USD GBP EUR HKD CNY TWD JPY SGD AUD CAD CHF KRW
max_trades = 3                 # at most this many cards in "Today's playbook" (1–6)

[email]
enabled = false
to = []                        # e.g. ["you@example.com"]
from = "Cheez Daily <cheez@example.com>"
provider = "smtp"              # smtp | resend
smtp_host = ""
smtp_port = 587
smtp_user = ""
include_portfolio = false
language = ""                  # "" = report.default_language
convert_to = ""                # "" = report.convert_to
page_url = ""                  # link to your private page, shown as the email's button
subject_prefix = "Cheez Daily"

[publish]
artifact_url = ""              # the private claude.ai page a Claude run republishes
```

### Delivery time

`deliver_at` is when you want to read it; the scheduled run starts
`lead_minutes` earlier (moved off :00 and :30, when scheduled tasks are
busiest). `cheez schedule` prints the cron line for the scheduled task, for
example `CRON_TZ=Europe/London 20 6 * * 1-5`. Writing the cron in your own
timezone means daylight-saving changes never move your delivery time.

Why 07:00 London by default: the previous US close, the overnight futures
session and the Asian close are all known; European markets open at 08:00, the
US at 14:30. You have the whole morning to think before anything US-listed can
be traded, rather than an hour. The trade-off is that US pre-market prices at
06:20 are thin overnight-session prints (labelled as such), and 08:30 New York
data releases (jobs, CPI) arrive after the edition; they are shown as pending.
If you want a second look closer to the open, add a manual revision (see
OPERATIONS.md).

The edition is always for the US session that opens on your local date. From
Asia, a 07:00 run is the previous evening in New York, and the edition covers
the session that opens that night your time.

### Languages

Each language beyond English costs one extra translation file per run (a few
minutes of the agent's time). Translations are checked against the English
edition: a translation that changes a number, ticker, level, action or link is
dropped and that language falls back to English, with a warning in the
Method section. To save run time, write fewer: `languages = ["en", "zh-Hant"]`.

Readers can switch language on the page; their choice is remembered in their
browser. `default_language` decides what a first-time reader and the email
see.

### Currency annotation

Off by default. When a reader picks a currency (or you set `convert_to`), every
price on the page gets a ruby annotation with the approximate equivalent:
stock prices, entry zones, invalidation levels, targets, portfolio values,
commodity prices and dollar amounts written in the prose ("$1.9bn"). Rates are
fetched once per run from Yahoo Finance and shown in the Method section.
Index points, yields and percentages are not converted. Conversions are for
reading only; the levels themselves stay in the instrument's own currency.

### Email

See [EMAIL.md](EMAIL.md).

## Environment variables

| Variable | Sets |
|---|---|
| `CHEEZ_CONFIG` | Path to a settings file |
| `CHEEZ_CONFIG_TOML` | The whole settings file as text |
| `CHEEZ_DELIVER_AT` | `schedule.deliver_at` |
| `CHEEZ_TIMEZONE` | `schedule.timezone` |
| `CHEEZ_LANGUAGE` | `report.default_language` |
| `CHEEZ_LANGUAGES` | `report.languages` (comma-separated) |
| `CHEEZ_CONVERT_TO` | `report.convert_to` |
| `CHEEZ_EMAIL_TO` | `email.to` (comma-separated); setting it also turns email on |
| `CHEEZ_EMAIL_FROM` | `email.from` |
| `CHEEZ_EMAIL_PROVIDER` | `email.provider` |
| `CHEEZ_SMTP_HOST`, `CHEEZ_SMTP_USER` | SMTP server and user |
| `CHEEZ_PAGE_URL` | `email.page_url` |
| `CHEEZ_ARTIFACT_URL` | `publish.artifact_url` |
| `CHEEZ_SMTP_PASSWORD` | SMTP password (secret; never in a settings file) |
| `CHEEZ_RESEND_API_KEY` | Resend API key (secret; or let the network proxy inject it) |
| `CHEEZ_HOME` | Private working directory (default `var/`) |

Brokerage variables are listed in [SETUP.md](SETUP.md).

## Examples

A reader in Taipei who wants Traditional Chinese and New Taiwan dollars, by
email at 06:45:

```toml
[schedule]
deliver_at = "06:45"
timezone = "Asia/Taipei"

[report]
default_language = "zh-Hant"
convert_to = "TWD"

[email]
enabled = true
to = ["me@example.com"]
provider = "resend"
from = "Cheez Daily <brief@mydomain.example>"
```

A reader in London who only wants English, and pounds on request:

```toml
[report]
languages = ["en"]
```
