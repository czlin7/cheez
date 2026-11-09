"""Edition lifecycle: prepare facts -> (model writes editorial) -> check -> render -> record.

Every step is idempotent and bounded. A run that is retried for the same US
trading date never produces a second edition: it is either skipped or, when
forced, published as a numbered revision of the same edition.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from . import session as sess
from .analytics import ledger as ledger_mod
from .analytics.portfolio import FxBook, account_view
from .config import MAX_HTTP_REQUESTS, STALE_RUN_HOURS, var_dir
from .editorial.validate import ValidationReport, validate
from .market import build_snapshot, snapshot_problems
from .models import Editorial, FxRate, MarketSnapshot, PortfolioSnapshot, RunRecord, StockFacts
from .net import Fetcher
from .render import site
from .state import MAX_ARCHIVE_EDITIONS, EditionEntry, State, Store, import_page
from .stocks import stock_facts

UTC = timezone.utc


class Pack(BaseModel):
    edition_id: str
    edition_date: date
    kind_label: str
    trigger: str
    revision: int = 1
    prepared_at: datetime
    market: MarketSnapshot
    stocks: dict[str, StockFacts] = Field(default_factory=dict)
    portfolio: PortfolioSnapshot
    candidates: dict = Field(default_factory=dict)
    problems: list[str] = Field(default_factory=list)
    demo: bool = False


class PrepareResult(BaseModel):
    outcome: str  # ready | closed | duplicate | in_progress
    edition_id: str
    message: str
    brief_path: Optional[str] = None
    editorial_path: Optional[str] = None


def kind_label(ctx) -> str:
    if not ctx.is_trading_day:
        return "Market-closed note"
    return {
        "pre_open": "US pre-market edition",
        "regular": "US intraday edition",
        "post_close": "US after-close edition",
        "overnight": "US after-close edition",
    }[ctx.phase]


def _store() -> Store:
    return Store(var_dir())


def _fetcher(offline: bool = False) -> Fetcher:
    return Fetcher(cache_dir=var_dir() / "cache", max_requests=MAX_HTTP_REQUESTS, offline=offline)


def _runs_for(st: State, eid: str) -> list[RunRecord]:
    return [r for r in st.runs if r.edition_id == eid]


def _fx_rates(f: Fetcher, snap: PortfolioSnapshot, now: datetime) -> list[FxRate]:
    from .market import fx_quote

    pairs: set[tuple[str, str]] = set()
    for a in snap.accounts:
        base = (a.base_currency or "USD").upper()
        for p in a.positions:
            if p.currency.upper() != base:
                pairs.add((p.currency.upper(), base))
        for c in a.cash:
            if c.currency.upper() != base:
                pairs.add((c.currency.upper(), base))
    out = []
    for a, b in sorted(pairs):
        q = fx_quote(f, a, b)
        if q:
            out.append(FxRate(pair=f"{a}{b}", rate=q[0], as_of=q[1] or now, source="Yahoo Finance"))
    return out


def _portfolio(f: Fetcher, now: datetime) -> PortfolioSnapshot:
    from .brokerage.longbridge import fetch_snapshot

    snap = fetch_snapshot(now)
    if snap.status in ("ok", "partial"):
        snap.fx = _fx_rates(f, snap, now)
    return snap


def prepare(now: Optional[datetime] = None, *, trigger: str = "manual", force: bool = False,
            state_from: Optional[Path] = None, offline: bool = False,
            portfolio_override: Optional[PortfolioSnapshot] = None, max_candidates: int = 14) -> PrepareResult:
    now = (now or datetime.now(tz=UTC)).replace(microsecond=0)
    store = _store()
    st = import_page(Path(state_from).read_text(), store) if state_from else store.load()
    ctx = sess.us_session_context(now)
    eid = sess.edition_id(ctx.edition_date, "us")
    prior = _runs_for(st, eid)
    done = [r for r in prior if r.status in ("succeeded", "partial", "skipped_closed")]
    running = [r for r in prior if r.status == "running" and now - r.started_at < timedelta(hours=STALE_RUN_HOURS)]
    if done and not force:
        st.runs.append(RunRecord(edition_id=eid, started_at=now, finished_at=now, status="skipped_duplicate",
                                 trigger=trigger, problems=["An edition for this date already exists."]))
        store.save(st)
        return PrepareResult(outcome="duplicate", edition_id=eid,
                             message=f"Edition {eid} already published; nothing to do. Use --force for a revision.")
    if running and not force:
        return PrepareResult(outcome="in_progress", edition_id=eid,
                             message=f"A run for {eid} started at {running[-1].started_at:%H:%M UTC} and has not finished.")
    for r in prior:  # interrupted runs are closed out, never resumed silently
        if r.status == "running":
            r.status = "failed"
            r.finished_at = now
            r.problems.append("Run did not finish (interrupted or timed out).")
    revision = max([r.revision for r in done], default=0) + 1 if done else 1

    f = _fetcher(offline)
    problems: list[str] = []
    market = build_snapshot(f, now)
    problems.extend(snapshot_problems(market))
    portfolio = portfolio_override or _portfolio(f, now)
    if portfolio.status == "error":
        problems.append("Portfolio data unavailable: " + " ".join(portfolio.messages))

    stocks: dict[str, StockFacts] = {}
    cands: dict = {}
    if ctx.is_trading_day:
        from .sources import movers
        from .sources.symbols import SymbolDirectory

        try:
            directory = SymbolDirectory.load(f)
        except Exception as e:
            directory = None
            problems.append(f"Symbol directory unavailable ({type(e).__name__}); identities are provider-only.")
        cerr: list[str] = []
        cands = movers.candidates(f, ctx.edition_date, cerr)
        problems.extend(cerr)
        wanted: list[str] = []
        for a in portfolio.accounts:
            for p in a.positions:
                if (p.market or "").upper() in ("US", "") and p.ticker.isalpha():
                    wanted.append(p.ticker)
        ranked_movers = sorted(cands.get("movers", []), key=lambda m: -abs(m.get("change_pct") or 0))
        wanted += [m["symbol"] for m in ranked_movers[: max_candidates // 2]]
        wanted += [r["symbol"] for r in cands.get("earnings_today", [])[: max_candidates // 2]]
        for t in dict.fromkeys(x.upper() for x in wanted if x):
            try:
                stocks[t] = stock_facts(f, t, now, directory)
            except Exception as e:
                problems.append(f"No price data for {t} ({type(e).__name__}).")
        # Price positions the broker did not price (e.g. quote entitlement missing).
        for a in portfolio.accounts:
            for p in a.positions:
                sf = stocks.get(p.ticker.upper())
                if p.last_price is None and sf and sf.last:
                    p.last_price, p.last_price_as_of, p.last_price_session = sf.last.value, sf.last.as_of, sf.last.session
                    p.market_value = p.last_price * p.quantity
    pack = Pack(edition_id=eid, edition_date=ctx.edition_date, kind_label=kind_label(ctx), trigger=trigger,
                revision=revision, prepared_at=now, market=market, stocks=stocks, portfolio=portfolio,
                candidates=cands, problems=problems)
    d = store.edition_dir(eid)
    for name in ("editorial.json", "validation.json"):  # never let a new revision reuse an old editorial
        old = d / name
        if old.exists():
            old.replace(d / f"{old.stem}.superseded-{now:%Y%m%dT%H%M%S}{old.suffix}")
    (d / "pack.json").write_text(pack.model_dump_json())
    (d / "brief.md").write_text(write_brief(pack, st))
    st.runs.append(RunRecord(edition_id=eid, started_at=now, status="running", revision=revision,
                             trigger=trigger if trigger in ("scheduled", "manual", "test", "demo") else "manual",
                             data_cutoff=market.data_cutoff))
    store.save(st)
    if not ctx.is_trading_day:
        return PrepareResult(outcome="closed", edition_id=eid, brief_path=str(d / "brief.md"),
                             message=f"US markets closed ({ctx.holiday_name or 'weekend'}). Run `cheez render --closed`.")
    return PrepareResult(outcome="ready", edition_id=eid, brief_path=str(d / "brief.md"),
                         editorial_path=str(d / "editorial.json"),
                         message=f"Facts ready for {eid}. Write the editorial to {d / 'editorial.json'}.")


def add_stocks(edition_id: str, symbols: list[str], offline: bool = False) -> dict[str, str]:
    from .sources.symbols import SymbolDirectory

    store = _store()
    d = store.edition_dir(edition_id)
    pack = Pack.model_validate_json((d / "pack.json").read_text())
    f = _fetcher(offline)
    try:
        directory = SymbolDirectory.load(f)
    except Exception:
        directory = None
    now = datetime.now(tz=UTC).replace(microsecond=0)
    out = {}
    for s in symbols:
        t = s.upper().strip()
        try:
            sf = stock_facts(f, t, now, directory)
            pack.stocks[t] = sf
            out[t] = "ambiguous: " + (sf.identity.note or "") if sf.identity.ambiguous else (sf.identity.name or "ok")
        except Exception as e:
            out[t] = f"failed: {type(e).__name__}"
    (d / "pack.json").write_text(pack.model_dump_json())
    st = store.load()
    (d / "brief.md").write_text(write_brief(pack, st))
    return out


def refresh(edition_id: str, offline: bool = False) -> dict:
    """Re-fetch prices for an edition in progress, so a long research step does
    not publish stale levels. Keeps the same run, revision and candidates."""
    store = _store()
    d = store.edition_dir(edition_id)
    pack = Pack.model_validate_json((d / "pack.json").read_text())
    now = datetime.now(tz=UTC).replace(microsecond=0)
    f = _fetcher(offline)
    from .sources.symbols import SymbolDirectory

    try:
        directory = SymbolDirectory.load(f)
    except Exception:
        directory = None
    market = build_snapshot(f, now)
    problems = [p for p in pack.problems if not p.startswith(("Missing:", "Stale:"))] + snapshot_problems(market)
    failed = []
    for t in list(pack.stocks):
        try:
            pack.stocks[t] = stock_facts(f, t, now, directory)
        except Exception:
            failed.append(t)
    pack.market, pack.problems = market, problems
    (d / "pack.json").write_text(pack.model_dump_json())
    st = store.load()
    (d / "brief.md").write_text(write_brief(pack, st))
    for r in st.runs:
        if r.edition_id == edition_id and r.status == "running":
            r.data_cutoff = market.data_cutoff
    store.save(st)
    return {"edition_id": edition_id, "data_cutoff": market.data_cutoff.isoformat(), "refreshed_stocks": len(pack.stocks),
            "failed": failed, "problems": problems}


def load_pack(edition_id: str) -> Pack:
    return Pack.model_validate_json((_store().edition_dir(edition_id) / "pack.json").read_text())


def latest_edition_id() -> Optional[str]:
    root = var_dir() / "editions"
    if not root.exists():
        return None
    ids = sorted(p.name for p in root.iterdir() if (p / "pack.json").exists())
    return ids[-1] if ids else None


def check(edition_id: str) -> tuple[Optional[Editorial], ValidationReport]:
    store = _store()
    d = store.edition_dir(edition_id)
    pack = load_pack(edition_id)
    st = store.load()
    rep = ValidationReport()
    p = d / "editorial.json"
    if not p.exists():
        rep.errors.append(f"{p} does not exist.")
        return None, rep
    try:
        ed = Editorial.model_validate_json(p.read_text())
    except Exception as e:
        rep.errors.append("Editorial does not match the schema: " + str(e)[:3000])
        return None, rep
    rep = validate(ed, edition_id=edition_id, session=pack.market.session, stocks=pack.stocks,
                   portfolio=pack.portfolio, ledger=st.ledger, instrument_keys={i.key for i in pack.market.instruments})
    (d / "validation.json").write_text(json.dumps({"errors": rep.errors, "warnings": rep.warnings}, indent=1))
    return ed, rep


def _status(pack: Pack, editorial_ok: bool) -> str:
    if pack.demo:
        return "demo"
    if not pack.market.session.is_trading_day:
        return "closed"
    if pack.problems or not editorial_ok:
        return "partial"
    return "complete"


def render(edition_id: str, *, closed: bool = False, market_only_reason: Optional[str] = None,
           now: Optional[datetime] = None) -> dict:
    """Render the edition and the publishable page; update ledger, archive and run log."""
    now = (now or datetime.now(tz=UTC)).replace(microsecond=0)
    store = _store()
    d = store.edition_dir(edition_id)
    pack = load_pack(edition_id)
    st = store.load()
    editorial: Optional[Editorial] = None
    rep: Optional[ValidationReport] = None
    if not closed and market_only_reason is None:
        editorial, rep = check(edition_id)
        if not rep.ok:
            raise SystemExit("Editorial failed validation:\n- " + "\n- ".join(rep.errors))
    problems = list(pack.problems)
    if market_only_reason:
        problems.append(f"Commentary and ideas unavailable: {market_only_reason}")
    status = _status(pack, editorial is not None or closed)
    if market_only_reason and status == "complete":
        status = "partial"

    if editorial is not None:
        histories = {k: v.history for k, v in pack.stocks.items()}
        ledger_mod.record_edition(st.ledger, editorial, pack.edition_date, pack.stocks, revision=pack.revision)
        ledger_mod.evaluate(st.ledger, histories, pack.edition_date)

    run = next((r for r in reversed(st.runs) if r.edition_id == edition_id and r.status == "running"), None)
    if run is None:  # a re-render of the same revision updates its record rather than adding another
        run = next((r for r in reversed(st.runs) if r.edition_id == edition_id and r.revision == pack.revision
                    and r.status != "skipped_duplicate"), None)
    if run is None:
        run = RunRecord(edition_id=edition_id, started_at=pack.prepared_at, status="running", revision=pack.revision)
        st.runs.append(run)
    run.status = {"complete": "succeeded", "demo": "succeeded", "closed": "skipped_closed"}.get(status, "partial")
    run.finished_at = now
    run.problems = problems
    run.data_cutoff = pack.market.data_cutoff

    meta = site.EditionMeta(
        id=edition_id, date=pack.edition_date, kind_label=pack.kind_label, published_at=now,
        data_cutoff=pack.market.data_cutoff, status=status, problems=problems, demo=pack.demo,
        revision=pack.revision, read_minutes=site._read_minutes(editorial),
        closed_headline=(pack.market.session.notes[0] if pack.market.session.notes else "US markets closed")
        if closed else ("Market data only today" if market_only_reason else ""),
        next_expected=None if pack.demo else site.next_expected_edition(pack.edition_date),
    )
    previous = None
    prev_eds = [e for e in st.editions if e.id != edition_id]
    if prev_eds:
        p = max(prev_eds, key=lambda e: (e.date, e.published_at))
        previous = {"id": p.id, "date": p.date, "headline": p.headline}
    translations: dict = {}
    if editorial is not None:
        from .editorial import translate
        from .settings import get as settings

        translations, tr_warnings = translate.load(d, editorial, settings().report.languages)
        rep.warnings.extend(tr_warnings)
    opts = site.render_options(pack.market, translations)
    with site.rendering(opts):
        view = site.build_view(edition=meta, market=pack.market, stocks=pack.stocks, editorial=editorial, report=rep,
                               portfolio=pack.portfolio, state=st, run=run, previous=previous)
        body = site.render_edition_body(view)

    headline = editorial.headline if editorial else meta.closed_headline
    st.editions = [e for e in st.editions if e.id != edition_id]
    st.editions.append(EditionEntry(id=edition_id, date=pack.edition_date, headline=headline, status=status,
                                    published_at=now))
    st.editions.sort(key=lambda e: (e.date, e.published_at))
    if editorial is not None:
        st.last_editorial = json.loads(editorial.model_dump_json())
    st.last_market = {i.key: (i.last.value if i.last else None) for i in pack.market.instruments}
    st.demo = pack.demo
    store.archive_put(edition_id, body)

    keep = [e.id for e in sorted(st.editions, key=lambda e: e.date, reverse=True)][:MAX_ARCHIVE_EDITIONS]
    archive_items = [(eid, store.archive_get(eid) or "") for eid in keep if eid != edition_id and store.archive_get(eid)]
    st.editions = [e for e in st.editions if e.id in keep]
    store.save(st)

    site_dir = var_dir() / ("site-demo" if pack.demo else "site")
    site_dir.mkdir(parents=True, exist_ok=True)
    with site.rendering(opts):
        index_fragment = site.assemble_index(body=body, view=view, state=st, archive_items=archive_items, document=False)
        index_doc = site.assemble_index(body=body, view=view, state=st, archive_items=archive_items, document=True)
        edition_doc = site.render_page(body=body, view=view, document=True, archive=None, home_href="../cheez-daily.html")
    (site_dir / "index.html").write_text(index_fragment)
    (site_dir / "cheez-daily.html").write_text(index_doc)
    (d / "edition.html").write_text(edition_doc)
    (d / "translations.json").write_text(json.dumps(translations, ensure_ascii=False))
    return {"status": status, "run_status": run.status, "publish_file": str(site_dir / "index.html"),
            "preview_file": str(site_dir / "cheez-daily.html"), "edition_file": str(d / "edition.html"),
            "problems": problems, "warnings": rep.warnings if rep else [],
            "bytes": len(index_fragment.encode())}


def fail(edition_id: Optional[str], reason: str, now: Optional[datetime] = None) -> dict:
    """Record a failed run. If market facts exist, publish them as a clearly
    labelled market-only edition rather than leaving yesterday's page up."""
    now = (now or datetime.now(tz=UTC)).replace(microsecond=0)
    store = _store()
    if edition_id and (store.edition_dir(edition_id) / "pack.json").exists():
        return render(edition_id, market_only_reason=reason, now=now)
    st = store.load()
    ctx = sess.us_session_context(now)
    eid = edition_id or sess.edition_id(ctx.edition_date, "us")
    st.runs.append(RunRecord(edition_id=eid, started_at=now, finished_at=now, status="failed", problems=[reason]))
    store.save(st)
    return {"status": "failed", "run_status": "failed", "publish_file": None, "problems": [reason]}


# ---------------------------------------------------------------------------
# The research brief handed to the model
# ---------------------------------------------------------------------------


def _fmt(v: Optional[float], dp: int = 2) -> str:
    return "n/a" if v is None else f"{v:,.{dp}f}"


def write_brief(pack: Pack, st: State) -> str:
    from .analytics.technicals import fact_keys
    from .render.format import when

    m = pack.market
    ctx = m.session
    L: list[str] = []
    L.append(f"# Cheez research brief — {pack.edition_id} ({pack.kind_label})")
    L.append("")
    L.append(f"Prepared {pack.prepared_at:%Y-%m-%d %H:%M} UTC. Data cut-off {m.data_cutoff:%H:%M} UTC. Revision {pack.revision}.")
    L.append(f"Session: {site.session_text(ctx)}. Trading day: {ctx.is_trading_day}. Early close: {ctx.early_close}.")
    for n in ctx.notes:
        L.append(f"- Note: {n}")
    if pack.problems:
        L.append("")
        L.append("## Data problems (state these plainly if they matter)")
        L.extend(f"- {p}" for p in pack.problems)
    L.append("")
    L.append("## Markets (computed; do not restate numbers differently)")
    L.append("key | instrument | kind | level | change | session/as-of | basis | stale")
    for i in m.instruments:
        chg = (f"{i.change_bp:+.1f} bp" if i.kind == "yield" and i.change_bp is not None
               else f"{i.change_pct:+.2f}%" if i.change_pct is not None else "n/a")
        L.append(f"{i.key} | {i.label} | {i.kind} | {_fmt(i.last.value if i.last else None, 4 if i.kind == 'fx' else 2)} | "
                 f"{chg} | {when(i.last, i.exchange_tz)} | {i.change_basis or ''} | {i.stale_reason or ''}")
    if st.last_market:
        L.append("")
        L.append("Previous edition's levels: " + ", ".join(f"{k}={_fmt(v)}" for k, v in st.last_market.items() if v is not None))
    L.append("")
    L.append("## Candidates nominated by screens (most are noise; feature only what the evidence supports)")
    for c in pack.candidates.get("movers", [])[:30]:
        L.append(f"- {c['symbol']} ({c.get('name')}): {c.get('change_pct') or 0:+.1f}% on list {c['list']}, "
                 f"cap ${(c.get('market_cap') or 0) / 1e9:,.0f}bn, as of {c.get('as_of')}")
    if pack.candidates.get("earnings_today"):
        L.append("")
        L.append("Earnings today (market value ≥ $10bn, Nasdaq.com calendar):")
        for r in pack.candidates["earnings_today"]:
            L.append(f"- {r['symbol']} {r['name']} — {r['time']}, cap {r.get('market_cap')}, EPS forecast {r.get('eps_forecast')}")
    L.append("")
    L.append("## Stock facts available for featuring and ideas")
    L.append("Use `cheez add-stocks SYMBOL ...` to add any other US-listed ticker before referring to it. "
             "Cite reference levels in `entry.basis` exactly by these keys.")
    for t, sf in sorted(pack.stocks.items()):
        tech = sf.technicals
        L.append("")
        L.append(f"### {t} — {sf.identity.name or '?'} ({sf.identity.exchange or '?'})"
                 + (" [IDENTITY AMBIGUOUS]" if sf.identity.ambiguous else ""))
        if sf.last:
            L.append(f"- Last {sf.last.value:,.2f} {sf.currency} ({when(sf.last)}); change vs prior close "
                     f"{_fmt(sf.change_pct_vs_close)}%")
        L.append(f"- 1m {_fmt(tech.return_1m_pct, 1)}%, 3m {_fmt(tech.return_3m_pct, 1)}%, from 52w high "
                 f"{_fmt(tech.drawdown_from_52w_high_pct, 1)}%, ATR14 {_fmt(tech.atr14)}, avg $ volume 20d "
                 f"{_fmt((tech.avg_dollar_volume_20d or 0) / 1e6, 0)}m")
        keys = fact_keys(tech)
        L.append("- Reference levels: " + ", ".join(f"{k}={v:,.2f}" for k, v in keys.items()))
        if sf.next_earnings:
            L.append(f"- Next earnings {sf.next_earnings} ({sf.next_earnings_source})")
    L.append("")
    L.append("## Portfolio (minimised: weights only; no cost basis, to avoid anchoring)")
    p = pack.portfolio
    if p.status in ("ok", "partial") and p.accounts:
        fx = FxBook.from_rates(p.fx)
        for a in p.accounts:
            av = account_view(a, fx)
            L.append(f"- {a.label}: base {a.base_currency}; positions {len(a.positions)}; largest weight "
                     f"{_fmt(av.top_weight_pct, 1)}%; effective positions {_fmt(av.effective_positions, 1)}")
            for pv in av.positions:
                pos = pv.position
                L.append(f"  - {pos.ticker} ({pos.market}): weight {_fmt(pv.weight_pct, 1)}%; sellable quantity "
                         f"{'yes' if (pos.available_quantity or 0) > 0 else 'none'}")
            for c in a.cash:
                L.append(f"  - Cash {c.currency}: free cash {'available' if (c.available or 0) > 0 else 'none'}")
            if a.open_orders:
                L.append(f"  - Open orders: {', '.join(f'{o.side} {o.symbol}' for o in a.open_orders)}")
            L.extend(f"  - Issue: {x}" for x in av.issues)
    else:
        L.append(f"- Status: {p.status}. {' '.join(p.messages)}")
        L.append("- Do not write personalised hold/add/trim/exit ideas; the validator will reject them.")
    if st.last_editorial:
        le = st.last_editorial
        L.append("")
        L.append(f"## Previous edition ({le.get('edition_id')}): {le.get('headline')}")
        for dv in le.get("developments", []):
            L.append(f"- Development: {dv.get('title')}")
        for fs in le.get("featured", []):
            L.append(f"- Featured: {fs.get('symbol')} — {fs.get('headline')}")
        for idea in le.get("ideas", []):
            e = idea.get("entry") or {}
            inv = idea.get("invalidation") or {}
            L.append(f"- Idea {idea.get('idea_id')}: {idea.get('action')} {idea.get('symbol')} zone "
                     f"{e.get('low')}-{e.get('high')} invalidation {inv.get('level')}")
    open_ideas = [e for e in st.ledger.entries if e.status == "open"]
    if open_ideas:
        L.append("")
        L.append("## Open ideas in the ledger (revise with revision_of = idea_id; never rewrite)")
        for e in open_ideas:
            o = e.outcome
            L.append(f"- {e.idea_id}: {e.action} {e.symbol} zone {e.entry_low}-{e.entry_high} inv {e.invalidation}; "
                     f"zone touched {o.zone_touched_on if o else None}; last close {o.last_close if o else None}")
    L.append("")
    L.append("Write editorial.json per .claude/skills/cheez-edition/SKILL.md, then run `cheez check`.")
    return "\n".join(L)
