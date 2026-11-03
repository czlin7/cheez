import os
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture()
def cheez_home(tmp_path, monkeypatch):
    """Isolated private working area for each test."""
    monkeypatch.setenv("CHEEZ_HOME", str(tmp_path / "var"))
    for k in ("CHEEZ_LONGBRIDGE_OAUTH", "CHEEZ_LONGBRIDGE_SCOPES", "LONGBRIDGE_APP_KEY", "LONGPORT_ACCESS_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path / "var"


@pytest.fixture()
def demo_world():
    from cheez import demo

    rng = random.Random(20261103)
    market = demo.demo_market(rng)
    stocks = demo.demo_stocks(rng)
    portfolio = demo.demo_portfolio(stocks)
    return market, stocks, portfolio


@pytest.fixture()
def offline_pipeline(monkeypatch, demo_world):
    """Pipeline wired to synthetic data: no network at all."""
    from cheez import pipeline
    from cheez.sources import movers

    market, stocks, portfolio = demo_world

    def fake_snapshot(f, now, specs=None):
        m = market.model_copy(deep=True)
        from cheez import session as sess

        m.session = sess.us_session_context(now)
        m.generated_at = now
        return m

    monkeypatch.setattr(pipeline, "build_snapshot", fake_snapshot)
    monkeypatch.setattr(pipeline, "_portfolio", lambda f, now: portfolio.model_copy(deep=True))
    monkeypatch.setattr(pipeline, "stock_facts", lambda f, t, now, d: stocks[t].model_copy(deep=True))
    monkeypatch.setattr(movers, "candidates", lambda f, today, errors=None: {
        "movers": [{"symbol": "NWSC", "name": "Northwind", "change_pct": 3.1, "market_cap": 9e10, "list": "day_gainers",
                    "as_of": None}], "earnings_today": []})

    class NoDir:
        @staticmethod
        def load(f):
            raise RuntimeError("offline")

    import cheez.sources.symbols as symbols

    monkeypatch.setattr(symbols, "SymbolDirectory", NoDir)
    return market, stocks, portfolio
