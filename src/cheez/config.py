"""Static configuration: the cross-asset dashboard, paths and run budgets.

The instrument list is chosen for usefulness to a US-focused, globally aware
private investor, not for completeness. Each row says what kind of instrument
it is, so an index is never confused with an ETF proxy or a futures contract.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]


def var_dir() -> Path:
    """Private working area (gitignored). Override with CHEEZ_HOME."""
    return Path(os.environ.get("CHEEZ_HOME", ROOT / "var"))


@dataclass(frozen=True)
class InstrumentDef:
    key: str
    label: str
    group: str
    kind: str
    symbol: str  # Yahoo symbol
    unit: str = "pts"
    calendar: Optional[str] = None  # exchange_calendars code for index session labels
    note: Optional[str] = None
    chart: bool = False  # include in the cross-asset small multiples


INSTRUMENTS: list[InstrumentDef] = [
    # United States
    InstrumentDef("spx", "S&P 500", "United States", "index", "^GSPC", calendar="XNYS", chart=True),
    InstrumentDef("ndx_comp", "Nasdaq Composite", "United States", "index", "^IXIC", calendar="XNYS"),
    InstrumentDef("dji", "Dow Jones Industrial Average", "United States", "index", "^DJI", calendar="XNYS"),
    InstrumentDef("rut", "Russell 2000", "United States", "index", "^RUT", calendar="XNYS"),
    InstrumentDef("es", "E-mini S&P 500 future", "United States", "index_future", "ES=F",
                  note="Front-month CME future; trades almost 24 hours, so it moves before the cash index opens."),
    InstrumentDef("nq", "E-mini Nasdaq-100 future", "United States", "index_future", "NQ=F"),
    InstrumentDef("vix", "Cboe Volatility Index (VIX)", "United States", "volatility_index", "^VIX", calendar="XNYS"),
    # Europe
    InstrumentDef("stoxx600", "STOXX Europe 600", "Europe", "index", "^STOXX", calendar="XETR"),
    InstrumentDef("ftse", "FTSE 100", "Europe", "index", "^FTSE", calendar="XLON"),
    InstrumentDef("dax", "DAX", "Europe", "index", "^GDAXI", calendar="XETR"),
    # Asia
    InstrumentDef("n225", "Nikkei 225", "Asia", "index", "^N225", calendar="XTKS"),
    InstrumentDef("hsi", "Hang Seng", "Asia", "index", "^HSI", calendar="XHKG"),
    InstrumentDef("shcomp", "Shanghai Composite", "Asia", "index", "000001.SS", calendar="XSHG"),
    InstrumentDef("kospi", "KOSPI", "Asia", "index", "^KS11", calendar="XKRX"),
    # Rates (Treasury rows are added from the official curve; this is the live proxy)
    InstrumentDef("tnx", "US 10-year yield (Cboe TNX, live)", "Rates", "yield", "^TNX", unit="%", calendar="XNYS",
                  note="Cboe index tracking the 10-year Treasury yield intraday."),
    # Currencies
    InstrumentDef("dxy", "US Dollar Index (ICE)", "Currencies", "dollar_index", "DX-Y.NYB", unit="pts", chart=True),
    InstrumentDef("eurusd", "EUR/USD", "Currencies", "fx", "EURUSD=X", unit="rate"),
    InstrumentDef("gbpusd", "GBP/USD", "Currencies", "fx", "GBPUSD=X", unit="rate"),
    InstrumentDef("usdjpy", "USD/JPY", "Currencies", "fx", "JPY=X", unit="rate"),
    InstrumentDef("usdcnh", "USD/CNH", "Currencies", "fx", "CNH=X", unit="rate"),
    # Commodities
    InstrumentDef("wti", "WTI crude oil future", "Commodities", "commodity_future", "CL=F", unit="USD/bbl", chart=True),
    InstrumentDef("brent", "Brent crude oil future", "Commodities", "commodity_future", "BZ=F", unit="USD/bbl"),
    InstrumentDef("gold", "Gold future (COMEX)", "Commodities", "commodity_future", "GC=F", unit="USD/oz", chart=True),
    InstrumentDef("copper", "Copper future (COMEX)", "Commodities", "commodity_future", "HG=F", unit="USD/lb"),
]

GROUP_ORDER = ["United States", "Europe", "Asia", "Rates", "Currencies", "Commodities"]

# FX pairs used for portfolio currency conversion (Yahoo symbols; 1 unit of the
# first currency in the second). Extended at runtime with whatever currencies the
# portfolio holds.
FX_SYMBOL = "{a}{b}=X"

# Run budgets: bounded work, never an endless loop.
MAX_HTTP_REQUESTS = 600
MAX_VALIDATION_ATTEMPTS = 3
STALE_INSTRUMENT_HOURS = 30  # a "live" price older than this (on a trading day) is stale
STALE_RUN_HOURS = 3  # a 'running' record older than this is treated as interrupted

READING_TZ = "Europe/London"
