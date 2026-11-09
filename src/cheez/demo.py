"""Demonstration edition built entirely from synthetic data.

Every company, ticker, price and holding here is fictional and generated from
a fixed seed, so the demo is reproducible and can never be mistaken for a live
report: it lives under var/demo/, its pages carry a "Demonstration" banner, and
its tickers do not exist.
"""

from __future__ import annotations

import json
import math
import os
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import session as sess
from .analytics.technicals import compute
from .config import INSTRUMENTS, ROOT
from .models import (
    Account, Bar, CashFlow, CashLine, Coverage, DisplayFx, Execution, FxRate, Identity, Instrument, MarketSnapshot,
    OpenOrder, PortfolioSnapshot, Position, Price, SourceStatus, StockFacts,
)

UTC = timezone.utc
DEMO_NOW = datetime(2026, 11, 3, 12, 40, tzinfo=UTC)  # 07:40 New York, before the open
FIXTURES = ROOT / "fixtures" / "demo"

LEVELS = {
    "spx": 6890.0, "ndx_comp": 23100.0, "dji": 47200.0, "rut": 2440.0, "es": 6905.0, "nq": 25600.0, "vix": 17.2,
    "stoxx600": 571.0, "ftse": 9680.0, "dax": 24150.0, "n225": 50100.0, "hsi": 25800.0, "shcomp": 3930.0,
    "kospi": 4050.0, "tnx": 4.18, "dxy": 99.6, "eurusd": 1.152, "gbpusd": 1.312, "usdjpy": 152.4, "usdcnh": 7.12,
    "wti": 61.4, "brent": 65.2, "gold": 3990.0, "copper": 5.05,
}

DEMO_FX = {"USD": 1.0, "GBP": 0.762, "EUR": 0.868, "HKD": 7.77, "CNY": 7.12, "TWD": 30.6, "JPY": 152.4,
           "SGD": 1.30, "AUD": 1.53, "CAD": 1.40, "CHF": 0.80, "KRW": 1435.0}

DEMO_STOCKS = {
    # ticker: (name, exchange, start price, drift, vol, avg volume shares)
    "NWSC": ("Northwind Semiconductor Corp. (fictional)", "Nasdaq", 142.0, 0.0006, 0.024, 9_000_000),
    "HLDX": ("Harbourline Data Systems Inc. (fictional)", "NYSE", 88.0, 0.0012, 0.017, 4_000_000),
    "QRTZ": ("Quartzline Equipment Co. (fictional)", "Nasdaq", 61.0, 0.0002, 0.021, 3_500_000),
    "MRDN": ("Meridian Consumer Brands (fictional)", "NYSE", 47.0, -0.0004, 0.014, 2_800_000),
}


def _walk(rng: random.Random, start: float, n: int, drift: float, vol: float) -> list[float]:
    xs = [start]
    for _ in range(n - 1):
        xs.append(xs[-1] * math.exp(drift + vol * rng.gauss(0, 1)))
    return xs


def _sessions(end: date, n: int) -> list[date]:
    out: list[date] = []
    d = end
    while len(out) < n:
        if sess.is_session(d):
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def demo_market(rng: random.Random) -> MarketSnapshot:
    ctx = sess.us_session_context(DEMO_NOW)
    days = _sessions(sess.previous_session(ctx.edition_date), 66)
    insts = []
    for spec in INSTRUMENTS:
        lvl = LEVELS[spec.key]
        vol = 0.009 if spec.kind in ("index", "index_future") else 0.004 if spec.kind in ("fx", "dollar_index") else 0.015
        series = list(reversed(_walk(rng, lvl, 66, 0.0, vol)))
        hist = [Bar(d=d, c=round(v, 4)) for d, v in zip(days, series)]
        prev = hist[-2].c
        last = hist[-1].c
        session = {"index_future": "futures_live", "commodity_future": "futures_live", "fx": "fx_live",
                   "dollar_index": "fx_live"}.get(spec.kind, "regular_close")
        as_of = DEMO_NOW - timedelta(minutes=4) if session != "regular_close" else datetime.combine(
            days[-1], datetime.min.time(), tzinfo=UTC) + timedelta(hours=21)
        inst = Instrument(key=spec.key, label=spec.label, group=spec.group, kind=spec.kind, symbol="DEMO",  # type: ignore[arg-type]
                          source="demo", unit=spec.unit, exchange_tz="America/New_York",
                          last=Price(value=last, as_of=as_of, session=session),  # type: ignore[arg-type]
                          reference=Price(value=prev, as_of=as_of, session="regular_close"),
                          change_abs=last - prev, change_pct=(last / prev - 1) * 100,
                          change_bp=(last - prev) * 100 if spec.kind == "yield" else None,
                          change_basis="vs previous close (synthetic)", history=hist,
                          delay_note="Synthetic demonstration data.")
        insts.append(inst)
    # Official-curve rows, as the live pipeline adds them from the US Treasury.
    for key, label, lvl in (("ust2y", "US 2-year Treasury yield", 3.58), ("ust10y", "US 10-year Treasury yield", 4.16)):
        series = list(reversed(_walk(random.Random(key), lvl, 66, 0.0, 0.006)))  # own seed: keeps stock data stable
        hist = [Bar(d=d, c=round(v, 3)) for d, v in zip(days, series)]
        as_of = datetime.combine(days[-1], datetime.min.time(), tzinfo=UTC) + timedelta(hours=20, minutes=30)
        idx = next(i for i, x in enumerate(insts) if x.group == "Rates")
        insts.insert(idx if key == "ust2y" else idx + 1, Instrument(
            key=key, label=label, group="Rates", kind="yield", symbol="DEMO", source="demo", unit="%",
            exchange_tz="America/New_York", last=Price(value=hist[-1].c, as_of=as_of, session="end_of_day"),
            reference=Price(value=hist[-2].c, as_of=as_of, session="end_of_day"), change_abs=hist[-1].c - hist[-2].c,
            change_bp=(hist[-1].c - hist[-2].c) * 100, change_basis="vs previous official close (synthetic)",
            history=hist, delay_note="Synthetic demonstration data."))
    fx = DisplayFx(per_usd=dict(DEMO_FX), as_of=DEMO_NOW - timedelta(minutes=4), source="Synthetic demonstration rates")
    return MarketSnapshot(generated_at=DEMO_NOW, data_cutoff=DEMO_NOW - timedelta(minutes=4), session=ctx,
                          instruments=insts, demo=True, display_fx=fx,
                          sources=[SourceStatus(source="Synthetic demonstration data", ok=True, fetched_at=DEMO_NOW,
                                                items=len(insts), detail="Seeded random walk; not market data.")])


def demo_stocks(rng: random.Random) -> dict[str, StockFacts]:
    ctx = sess.us_session_context(DEMO_NOW)
    days = _sessions(sess.previous_session(ctx.edition_date), 252)
    out = {}
    for t, (name, exch, start, drift, vol, avgvol) in DEMO_STOCKS.items():
        closes = _walk(rng, start, 252, drift, vol)
        bars = []
        for d, c in zip(days, closes):
            hi = c * (1 + abs(rng.gauss(0, vol / 2)))
            lo = c * (1 - abs(rng.gauss(0, vol / 2)))
            bars.append(Bar(d=d, o=round(c * (1 + rng.gauss(0, vol / 4)), 2), h=round(hi, 2), l=round(lo, 2),
                            c=round(c, 2), v=float(int(avgvol * (0.6 + rng.random())))))
        close = bars[-1].c
        pre = round(close * (1 + rng.gauss(0, 0.012)), 2)
        sf = StockFacts(
            identity=Identity(symbol=t, name=name, exchange=exch, verified_by="demo_fixture"),
            last=Price(value=pre, as_of=DEMO_NOW - timedelta(minutes=6), session="pre_market"),
            regular_close=Price(value=close, as_of=datetime.combine(days[-1], datetime.min.time(), tzinfo=UTC)
                                + timedelta(hours=21), session="regular_close"),
            change_pct_vs_close=(pre / close - 1) * 100, technicals=compute(bars), history=bars,
            next_earnings=date(2026, 11, 19) if t == "NWSC" else None,
            next_earnings_source="Demo fixture" if t == "NWSC" else None, source="demo",
            delay_note="Synthetic demonstration data.",
        )
        out[t] = sf
    return out


def demo_portfolio(stocks: dict[str, StockFacts]) -> PortfolioSnapshot:
    px = {t: s.last.value for t, s in stocks.items() if s.last}
    acct = Account(
        label="Demo account", account_channel="lb", base_currency="USD", net_assets=None, total_cash=None,
        margin_or_financing_note="Buying power reported by the broker includes margin and is not treated as cash.",
        cash=[CashLine(currency="USD", cash_balance=6120.40, available=6120.40, withdrawable=6120.40, frozen=0, settling=0),
              CashLine(currency="HKD", cash_balance=15400.00, available=15400.00, withdrawable=15400.00, frozen=0, settling=0)],
        positions=[
            Position(symbol="HLDX.US", ticker="HLDX", name="Harbourline Data Systems (fictional)", market="US", currency="USD",
                     quantity=180, available_quantity=180, cost_price=61.20, last_price=px["HLDX"],
                     last_price_as_of=DEMO_NOW, last_price_session="pre_market", market_value=180 * px["HLDX"]),
            Position(symbol="MRDN.US", ticker="MRDN", name="Meridian Consumer Brands (fictional)", market="US", currency="USD",
                     quantity=120, available_quantity=120, cost_price=None,
                     cost_price_note="Broker did not report a cost price.", last_price=px["MRDN"],
                     last_price_as_of=DEMO_NOW, last_price_session="pre_market", market_value=120 * px["MRDN"]),
            Position(symbol="9999.HK", ticker="9999.HK", name="Fictional HK Holding", market="HK", currency="HKD",
                     quantity=400, available_quantity=400, cost_price=118.0, last_price=126.5,
                     last_price_as_of=DEMO_NOW - timedelta(hours=5), last_price_session="regular_close",
                     market_value=400 * 126.5),
        ],
        open_orders=[OpenOrder(symbol="QRTZ", side="buy", quantity=20, executed_quantity=0, price=55.0, order_type="LO",
                               status="New", submitted_at=DEMO_NOW - timedelta(days=1), currency="USD")],
        executions=[Execution(trade_id="demo1", symbol="HLDX", side="buy", quantity=180, price=61.2,
                              executed_at=datetime(2026, 3, 12, 15, 2, tzinfo=UTC))],
        cash_flows=[CashFlow(flow_id="d1", kind="deposit", currency="USD", amount=15000, at=datetime(2026, 3, 10, tzinfo=UTC)),
                    CashFlow(flow_id="d2", kind="dividend", currency="USD", amount=21.6, at=datetime(2026, 9, 15, tzinfo=UTC))],
        executions_coverage=Coverage(requested_from=date(2025, 11, 3), requested_to=date(2026, 11, 3),
                                     retrieved_from=date(2026, 3, 12), retrieved_to=date(2026, 11, 3), records=1,
                                     complete=False, note="Demo history window."),
        cash_flows_coverage=Coverage(requested_from=date(2025, 11, 3), requested_to=date(2026, 11, 3),
                                     retrieved_from=date(2025, 11, 3), retrieved_to=date(2026, 11, 3), records=2,
                                     complete=False),
    )
    snap = PortfolioSnapshot(status="ok", provider="demo", retrieved_at=DEMO_NOW, as_of=DEMO_NOW, accounts=[acct],
                             fx=[FxRate(pair="HKDUSD", rate=0.1286, as_of=DEMO_NOW, source="Demo fixture")],
                             messages=["Fictional demonstration portfolio."], demo=True)
    inv = sum(p.market_value or 0 for p in acct.positions if p.currency == "USD") + 400 * 126.5 * 0.1286
    acct.net_assets = round(inv + 6120.40 + 15400 * 0.1286, 2)
    return snap


def build_demo(live_market: bool = False) -> dict:
    """Write the demo edition under var/demo and return the output paths."""
    from .config import var_dir

    home = var_dir() / "demo"
    os.environ["CHEEZ_HOME"] = str(home)
    from . import pipeline
    from .state import State, Store

    store = Store(home)
    store.save(State(demo=True))  # the demo always starts from a clean history
    for p in store.archive_dir.glob("*.html"):
        p.unlink()
    rng = random.Random(20261103)
    market = demo_market(rng)
    stocks = demo_stocks(rng)
    portfolio = demo_portfolio(stocks)
    ctx = market.session
    eid = sess.edition_id(ctx.edition_date, "us")
    pack = pipeline.Pack(edition_id=eid, edition_date=ctx.edition_date, kind_label="US pre-market edition",
                         trigger="demo", prepared_at=DEMO_NOW, market=market, stocks=stocks, portfolio=portfolio,
                         candidates={}, problems=[], demo=True)
    d = store.edition_dir(eid)
    (d / "pack.json").write_text(pack.model_dump_json())
    ed = json.loads((FIXTURES / "editorial.json").read_text())
    ed["edition_id"] = eid
    (d / "editorial.json").write_text(json.dumps(ed, indent=1))
    for tr in FIXTURES.glob("editorial.*.json"):  # parallel translations, same shape
        t = json.loads(tr.read_text())
        t["edition_id"] = eid
        (d / tr.name).write_text(json.dumps(t, ensure_ascii=False, indent=1))
    st = store.load()
    (d / "brief.md").write_text(pipeline.write_brief(pack, st))
    out = pipeline.render(eid, now=DEMO_NOW + timedelta(minutes=35))
    from .delivery import email as mail

    out["email_preview"] = str(mail.build(eid).html_path)
    _ = live_market
    return out


def print_demo_facts() -> None:  # helper used while authoring the demo editorial
    rng = random.Random(20261103)
    demo_market(rng)
    stocks = demo_stocks(rng)
    from .analytics.technicals import fact_keys

    for t, s in stocks.items():
        print(t, s.last.value, s.regular_close.value, {k: round(v, 2) for k, v in fact_keys(s.technicals).items()},
              s.technicals.avg_dollar_volume_20d)


if __name__ == "__main__":
    print_demo_facts()
