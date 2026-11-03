# Cheez

**Cheez Daily** is a private, read-only market briefing for one investor. Each
US trading day, before the open, it publishes a five-to-eight-minute edition
to a private page that reads well on a phone and a laptop:

- **The brief**: the few developments that matter, why, and what is not yet known, with sources beside each claim.
- **Markets**: US, European and Asian indices, futures, Treasury yields, the dollar, oil, gold and copper. Each value is labelled with its session, timestamp and the reference its change is measured against. Charts have labelled axes and time ranges.
- **Stocks in focus**: two to four names chosen on the day's evidence, whether or not you own them, with second-order read-throughs labelled as established or hypothesis.
- **Decisions and ideas**: ranked, long-only, cash-account ideas. Each one has a thesis, catalyst, an entry zone derived from computed price levels, the conditions before acting, an invalidation level and its gap risk, scenarios, costs and risks, and the strongest case against it. When nothing clears the bar, the edition says so; there is no daily quota.
- **Your portfolio**, read-only from Longbridge: allocation, concentration, cash by currency (never margin buying power), open orders, and how today's ideas would fit.
- **Idea record**: every published idea, never edited, with dated revisions and observed outcomes. A zone touch is not counted as a fill.

Numbers come from code; Claude does the research and writing; a validator
rejects unsupported levels, certainty language, shorting, margin, options and
personalised calls made without portfolio data.

## How it runs

A Claude Code scheduled task (`CRON_TZ=America/New_York 41 7 * * 1-5`) starts a
fresh cloud session each weekday. The session runs `cheez prepare`, researches
and writes following `.claude/skills/cheez-edition/SKILL.md`, then runs
`cheez check` and `cheez render`, and republishes the private artifact. The
edition is usually ready about 13:15 London time. Holidays get a short
market-closed note.

## Documents

- [docs/SETUP.md](docs/SETUP.md): one-time steps (read-only Longbridge connection, data-source decision)
- [docs/OPERATIONS.md](docs/OPERATIONS.md): schedule, manual refresh, pause, status, costs, maintenance
- [docs/SECURITY.md](docs/SECURITY.md): the read-only boundary, data flows, privacy
- [docs/DECISIONS.md](docs/DECISIONS.md): architecture choices and assumptions

## Commands

```text
cheez prepare [--trigger scheduled|manual] [--force] [--state-from PAGE]   facts + research brief
cheez add-stocks TICKER ...       verify identity and add facts for more tickers
cheez refresh                     re-fetch prices for the edition in progress
cheez check                       validate var/editions/<id>/editorial.json
cheez render [--closed]           build the page (var/site/index.html)
cheez fail "reason"               publish a labelled market-data-only edition
cheez status                      recent runs
cheez demo                        fictional demonstration edition (var/demo/)
cheez brokerage-check             show the read-only token's scopes and expiry
cheez brokerage-authorize         one-time: exchange a Longbridge Agent Auth Code (read-only scopes only)
```

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[brokerage,dev]'
python -m pytest -q
```

This repository is public. Editions, portfolio data and tokens never enter it:
everything private stays under the gitignored `var/` directory or in the
private artifact.

Cheez is a research tool, not investment advice, and it never places or
changes orders.
