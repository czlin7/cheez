"""Ticker identity verification against Nasdaq Trader's official symbol directory.

nasdaqlisted.txt covers Nasdaq-listed securities; otherlisted.txt covers NYSE,
NYSE American, NYSE Arca, Cboe BZX and IEX listings. Both are published daily by
Nasdaq. A ticker that is absent, a test issue, or matched only loosely is marked
as unverified/ambiguous so the validator blocks it rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Identity
from ..net import Fetcher

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
EXCHANGE_CODES = {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}


@dataclass
class Listing:
    symbol: str
    name: str
    exchange: str
    etf: bool
    lot: Optional[int]


class SymbolDirectory:
    def __init__(self, listings: dict[str, Listing]):
        self.listings = listings

    @classmethod
    def load(cls, f: Fetcher) -> "SymbolDirectory":
        out: dict[str, Listing] = {}
        raw = f.get(NASDAQ_LISTED, max_age=12 * 3600).decode("utf-8", "replace")
        for line in raw.splitlines()[1:]:
            p = line.split("|")
            if len(p) < 8 or p[3] == "Y":  # skip test issues and the trailer line
                continue
            out[p[0]] = Listing(p[0], p[1], "Nasdaq", p[6] == "Y", int(p[5]) if p[5].isdigit() else None)
        raw = f.get(OTHER_LISTED, max_age=12 * 3600).decode("utf-8", "replace")
        for line in raw.splitlines()[1:]:
            p = line.split("|")
            if len(p) < 8 or p[6] == "Y":
                continue
            sym = p[0].replace(".", "-")  # CQS uses '.', Yahoo uses '-' (e.g. BRK.B -> BRK-B)
            out.setdefault(sym, Listing(sym, p[1], EXCHANGE_CODES.get(p[2], p[2]), p[4] == "Y",
                                        int(p[5]) if p[5].isdigit() else None))
        return cls(out)

    def identify(self, ticker: str) -> Identity:
        t = ticker.upper().strip().replace(".", "-")
        hit = self.listings.get(t)
        if hit:
            return Identity(symbol=t, name=hit.name.strip(), exchange=hit.exchange,
                            verified_by="nasdaqtrader_symbol_directory",
                            note="ETF" if hit.etf else None)
        return Identity(symbol=t, ambiguous=True,
                        note="Not found in the US listed-securities directory; may be non-US, delisted or mistyped.")

    def is_etf(self, ticker: str) -> bool:
        hit = self.listings.get(ticker.upper())
        return bool(hit and hit.etf)
