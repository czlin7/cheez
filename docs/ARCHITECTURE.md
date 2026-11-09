# Architecture

## Layout

```text
cheez/
├── src/cheez/
│   ├── cli.py              command line (`cheez …`)
│   ├── pipeline.py         edition lifecycle: prepare → (agent writes) → check → render → record
│   ├── settings.py         user settings: delivery time, timezone, languages, currency, email
│   ├── schedule.py         cron line and scheduled-task prompt from settings
│   ├── session.py          NYSE calendar, which session an edition is for, session labels
│   ├── market.py           cross-asset snapshot and display FX rates
│   ├── stocks.py           per-ticker facts (prices, technicals, earnings date)
│   ├── models.py           data contracts (facts, editorial, ledger) — pydantic, extra="forbid"
│   ├── i18n.py             interface strings in English, 繁體中文, 简体中文
│   ├── state.py            ledger, run log and archive, embedded in the published page
│   ├── config.py           static configuration: instruments, budgets, paths
│   ├── net.py              bounded, cached HTTP fetcher
│   ├── sources/            Yahoo Finance, Nasdaq, US Treasury, symbol directory, movers
│   ├── analytics/          technicals, portfolio arithmetic, idea ledger
│   ├── brokerage/          the only code that touches Longbridge (read-only allowlist)
│   ├── editorial/
│   │   ├── validate.py     what makes an editorial publishable
│   │   └── translate.py    translations may change words, never facts
│   ├── render/
│   │   ├── site.py         view model: playbook, pulse, charts, portfolio
│   │   ├── format.py       filters: prices (with currency ruby), times in the reader's zone, i18n
│   │   ├── charts.py       server-side SVG line charts and sparklines
│   │   ├── templates/      page, edition body, email
│   │   └── static/         CSS, JS (settings, language switch, conversions), logo
│   ├── delivery/email.py   email digest: build, SMTP or Resend
│   └── demo.py             fictional demonstration edition
├── fixtures/demo/          demo editorial and its translations
├── tests/                  pytest suite (no network)
├── .claude/                skill (the runbook), guard hook, settings
├── AGENTS.md               instructions for non-Claude agents
├── assets/                 logo, wordmark, app icon
├── scripts/                screenshots, demo translation generator
└── docs/
```

## Three kinds of data

1. **Facts** (`MarketSnapshot`, `StockFacts`, `PortfolioSnapshot`) are produced
   by code from data sources. Every number in the report comes from here.
2. **Editorial** (`Editorial`, plus one parallel file per extra language) is
   written by the agent. It may reference facts; every proposed level is
   validated against them.
3. **History** (`Ledger`, `RunRecord`, archive) is append-only and travels
   inside the published page, because a scheduled cloud session starts empty.

## An edition, step by step

```text
cheez prepare     session context for the reader's date → market snapshot (+ display FX)
                  → movers and earnings → stock facts → read-only portfolio → brief.md
agent             research → editorial.json (+ editorial.zh-Hant.json, editorial.zh-Hans.json)
cheez check       schema + validator (levels near computed references, language rules, scope)
cheez render      ledger update → translations checked → view model → edition body
                  → page with archive and state → var/site/index.html
publish           Claude: artifact; any agent: cheez email --send
```

## Rendering choices

- **One body, three languages.** Each localisable element is rendered in the
  default language and carries the others as `data-en`, `data-zh-hant`,
  `data-zh-hans` attributes. The page switches without a reload; with scripts
  off it still reads correctly. Archived editions keep their own translations.
- **Prices are `<ruby class="m" data-v data-c>`.** With no annotation, a ruby
  element renders as plain text. Choosing a currency adds an `<rt>` with the
  conversion from rates embedded in each edition. Dollar amounts inside prose
  are found after escaping and wrapped the same way. Email uses inline
  "(≈ …)" text instead, since mail clients render ruby unevenly.
- **Render options** (timezone, language, currency, translations) are a
  context variable set around each render, so filters stay pure functions of
  their arguments plus that context.
- **Charts** are server-side SVG with labelled axes; sparklines are tiny SVGs
  coloured by direction; the email uses Unicode block sparklines.
