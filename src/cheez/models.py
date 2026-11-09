"""Data contracts shared by every stage of the Cheez pipeline.

Three kinds of data flow through Cheez and they are kept strictly separate:

* Deterministic facts (``MarketSnapshot``, ``StockFacts``, ``PortfolioSnapshot``)
  are produced by code from data sources. Numbers in the report come from here.
* Editorial judgement (``Editorial``) is written by the language model. It may
  reference facts, but every price level it proposes is validated against the
  facts before anything is rendered.
* Durable history (``Ledger``, ``RunRecord``) records what was published and
  what happened afterwards. It is append-only by design.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Market facts
# ---------------------------------------------------------------------------

InstrumentKind = Literal[
    "index",
    "index_future",
    "etf",
    "stock",
    "yield",
    "fx",
    "dollar_index",
    "commodity_future",
    "commodity_spot",
    "volatility_index",
]

# How a price was formed. Never mix these without saying so.
SessionLabel = Literal[
    "regular_close",  # official close of the last regular session
    "regular_live",  # during the regular session (may be delayed)
    "pre_market",  # US extended hours before the open (04:00-09:30 ET)
    "post_market",  # US extended hours after the close (16:00-20:00 ET)
    "overnight",  # US overnight session (20:00-04:00 ET)
    "futures_live",  # near-24h futures trading
    "end_of_day",  # official end-of-day fixing / published curve
    "fx_live",  # OTC FX, trades around the clock on weekdays
    "unknown",
]

SESSION_TEXT: dict[str, str] = {
    "regular_close": "Close",
    "regular_live": "Live",
    "pre_market": "Pre-market",
    "post_market": "After-hours",
    "overnight": "Overnight",
    "futures_live": "Live",
    "end_of_day": "End of day",
    "fx_live": "Live",
    "unknown": "Unlabelled",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Price(Strict):
    value: float
    as_of: datetime  # timezone-aware, UTC
    session: SessionLabel
    note: Optional[str] = None


class Bar(Strict):
    d: date
    o: Optional[float] = None
    h: Optional[float] = None
    l: Optional[float] = None
    c: float
    v: Optional[float] = None


class Instrument(Strict):
    key: str
    label: str
    group: str  # e.g. "US equities", "Europe", "Asia", "Rates", "Currencies", "Commodities"
    kind: InstrumentKind
    symbol: str  # provider symbol, shown in the source notes
    source: str  # provider id, e.g. "yahoo", "treasury"
    source_url: Optional[str] = None
    currency: Optional[str] = None
    unit: str = "pts"  # "pts", "%", "USD", "USD/bbl", "USD/oz", "rate"
    exchange_tz: Optional[str] = None
    last: Optional[Price] = None
    reference: Optional[Price] = None  # what the change is measured against
    change_abs: Optional[float] = None
    change_pct: Optional[float] = None
    change_bp: Optional[float] = None  # yields only, in basis points
    change_basis: Optional[str] = None  # human text, e.g. "vs Mon 2 Nov close"
    history: list[Bar] = Field(default_factory=list)  # daily closes, oldest first
    stale: bool = False
    stale_reason: Optional[str] = None
    delay_note: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class SessionContext(Strict):
    """Where the primary market (NYSE) is in its trading day at data cutoff."""

    exchange: str = "XNYS"
    edition_date: date  # the US trading date this edition is written for
    is_trading_day: bool
    phase: Literal["closed_day", "pre_open", "regular", "post_close", "overnight"]
    open_utc: Optional[datetime] = None
    close_utc: Optional[datetime] = None
    early_close: bool = False
    previous_session: Optional[date] = None
    next_session: Optional[date] = None
    holiday_name: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class SourceStatus(Strict):
    source: str
    ok: bool
    fetched_at: datetime
    detail: Optional[str] = None
    items: int = 0


class DisplayFx(Strict):
    """Rates used only to annotate prices in the reader's chosen currency."""

    per_usd: dict[str, float] = Field(default_factory=dict)  # 1 USD = rate CCY
    as_of: Optional[datetime] = None
    source: str = "Yahoo Finance"


class MarketSnapshot(Strict):
    generated_at: datetime
    data_cutoff: datetime
    session: SessionContext
    instruments: list[Instrument] = Field(default_factory=list)
    sources: list[SourceStatus] = Field(default_factory=list)
    display_fx: DisplayFx = Field(default_factory=DisplayFx)
    demo: bool = False


# ---------------------------------------------------------------------------
# Stock facts used to ground featured stocks and ideas
# ---------------------------------------------------------------------------


class Identity(Strict):
    symbol: str  # canonical ticker, e.g. "NVDA"
    name: Optional[str] = None
    exchange: Optional[str] = None
    cik: Optional[str] = None
    verified_by: Optional[str] = None  # e.g. "sec_company_tickers", "longbridge_static_info"
    ambiguous: bool = False
    note: Optional[str] = None


class Technicals(Strict):
    last_close: Optional[float] = None
    last_close_date: Optional[date] = None
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    high_20d: Optional[float] = None
    low_20d: Optional[float] = None
    atr14: Optional[float] = None
    drawdown_from_52w_high_pct: Optional[float] = None
    return_1m_pct: Optional[float] = None
    return_3m_pct: Optional[float] = None
    avg_dollar_volume_20d: Optional[float] = None
    swing_lows: list[tuple[date, float]] = Field(default_factory=list)
    swing_highs: list[tuple[date, float]] = Field(default_factory=list)
    history_days: int = 0


class StockFacts(Strict):
    identity: Identity
    currency: str = "USD"
    last: Optional[Price] = None  # most recent print, any session (labelled)
    regular_close: Optional[Price] = None  # last regular-session close
    change_pct_vs_close: Optional[float] = None
    technicals: Technicals = Field(default_factory=Technicals)
    history: list[Bar] = Field(default_factory=list)
    next_earnings: Optional[date] = None
    next_earnings_source: Optional[str] = None
    source: str = "yahoo"
    delay_note: Optional[str] = None
    stale: bool = False
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Portfolio facts (read-only brokerage snapshot, sanitised)
# ---------------------------------------------------------------------------


class CashLine(Strict):
    currency: str
    cash_balance: Optional[float] = None  # total cash in this currency (can be negative when financed)
    available: Optional[float] = None  # provider's "available cash" (cash only, excludes margin)
    withdrawable: Optional[float] = None
    frozen: Optional[float] = None
    settling: Optional[float] = None


class Position(Strict):
    symbol: str  # broker symbol, e.g. "AAPL.US", "700.HK"
    ticker: str  # plain ticker used for research, e.g. "AAPL"
    name: Optional[str] = None
    market: Optional[str] = None  # "US", "HK", ...
    currency: str
    quantity: float
    available_quantity: Optional[float] = None
    cost_price: Optional[float] = None  # per share, as reported by the broker
    cost_price_note: Optional[str] = None
    last_price: Optional[float] = None
    last_price_as_of: Optional[datetime] = None
    last_price_session: Optional[SessionLabel] = None
    market_value: Optional[float] = None  # quantity * last_price, in position currency
    lot_size: Optional[int] = None
    sector: Optional[str] = None
    themes: list[str] = Field(default_factory=list)


class OpenOrder(Strict):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    executed_quantity: float = 0
    price: Optional[float] = None
    order_type: Optional[str] = None
    status: str
    submitted_at: Optional[datetime] = None
    currency: Optional[str] = None


class Execution(Strict):
    """A filled trade (not an order, not a cancellation)."""

    trade_id: str  # hashed/opaque; used only for de-duplication
    symbol: str
    side: Optional[Literal["buy", "sell"]] = None
    quantity: float
    price: float
    executed_at: datetime
    currency: Optional[str] = None


class CashFlow(Strict):
    flow_id: str
    kind: str  # normalised: deposit, withdrawal, dividend, fee, interest, fx, trade, corporate_action, other
    currency: str
    amount: float  # signed, in currency
    at: datetime
    symbol: Optional[str] = None
    description: Optional[str] = None


class Coverage(Strict):
    requested_from: Optional[date] = None
    requested_to: Optional[date] = None
    retrieved_from: Optional[date] = None
    retrieved_to: Optional[date] = None
    records: int = 0
    complete: bool = False
    note: Optional[str] = None


class Account(Strict):
    label: str  # e.g. "Account 1" — never the broker account number
    account_channel: Optional[str] = None
    base_currency: Optional[str] = None
    net_assets: Optional[float] = None  # broker-reported, in base_currency
    total_cash: Optional[float] = None  # broker-reported, in base_currency
    margin_or_financing_note: Optional[str] = None
    cash: list[CashLine] = Field(default_factory=list)
    positions: list[Position] = Field(default_factory=list)
    open_orders: list[OpenOrder] = Field(default_factory=list)
    executions: list[Execution] = Field(default_factory=list)
    cash_flows: list[CashFlow] = Field(default_factory=list)
    executions_coverage: Coverage = Field(default_factory=Coverage)
    cash_flows_coverage: Coverage = Field(default_factory=Coverage)


class FxRate(Strict):
    pair: str  # "USDGBP" means 1 USD = rate GBP
    rate: float
    as_of: datetime
    source: str


class PortfolioSnapshot(Strict):
    status: Literal["ok", "partial", "unconfigured", "error", "stale"]
    provider: str = "longbridge"
    retrieved_at: Optional[datetime] = None
    as_of: Optional[datetime] = None
    accounts: list[Account] = Field(default_factory=list)
    fx: list[FxRate] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
    demo: bool = False


# ---------------------------------------------------------------------------
# Editorial (written by the language model, validated before rendering)
# ---------------------------------------------------------------------------


class SourceRef(Strict):
    title: str
    url: str
    publisher: Optional[str] = None
    published_at: Optional[str] = None  # ISO date or datetime as stated by the source
    event_date: Optional[str] = None  # when the thing happened, if different
    kind: Literal["filing", "company", "official", "news", "data", "analysis", "other"] = "news"


EvidenceStatus = Literal["established", "developing", "uncertain"]


class Development(Strict):
    title: str
    summary: str  # what happened
    why_it_matters: str
    status: EvidenceStatus
    uncertainty: Optional[str] = None  # what is not yet known
    tickers: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(min_length=1)


class MarketNote(Strict):
    instrument_key: str
    comment: str


class MarketRead(Strict):
    summary: str
    notes: list[MarketNote] = Field(default_factory=list)
    attribution_caveat: Optional[str] = None


class ReadThrough(Strict):
    symbol: str
    name: str
    relation: Literal["supplier", "customer", "competitor", "peer", "partner", "adjacent"]
    mechanism: str  # economic transmission mechanism
    materiality: str
    priced_in: str  # whether the effect may already be reflected in prices
    label: Literal["established", "hypothesis"]
    sources: list[SourceRef] = Field(default_factory=list)


class FeaturedStock(Strict):
    symbol: str
    headline: str
    catalyst: str
    why_attention: str
    interpretation: str
    is_new_since_last: bool = True
    status: EvidenceStatus = "established"
    read_throughs: list[ReadThrough] = Field(default_factory=list)
    sources: list[SourceRef] = Field(min_length=1)


ActionType = Literal["consider_buying", "consider_adding", "hold", "consider_trimming", "consider_exiting", "wait", "watch"]
ConfidenceLabel = Literal["low", "moderate", "high"]


class PriceZone(Strict):
    low: float
    high: float
    derivation: str  # how the zone was derived (must reference facts)
    basis: list[str] = Field(default_factory=list)  # fact keys used, e.g. ["sma50", "swing_low:2026-10-15"]


class Invalidation(Strict):
    level: float
    meaning: Literal["reassess", "consider_exit"]
    derivation: str
    gap_risk: str  # why a level is not a guaranteed exit price


class Scenario(Strict):
    name: str  # e.g. "Base", "Upside"
    target: Optional[float] = None
    horizon: str
    rationale: str


class Horizon(Strict):
    label: str  # e.g. "3-6 months"
    min_days: int
    max_days: int


class Idea(Strict):
    idea_id: str  # stable across editions, e.g. "2026-11-03-NVDA"
    symbol: str
    action: ActionType
    decision_today: bool  # is this a decision worth considering today (vs. a watch item)
    horizon: Horizon
    summary: Optional[str] = Field(None, max_length=200)  # one line for the playbook card: why this name, today
    outlook: Optional[str] = Field(None, max_length=240)  # what we expect, conditionally, over the horizon
    thesis: str
    why_now: str
    catalyst: str
    entry: Optional[PriceZone] = None  # required for consider_buying / consider_adding
    conditions: list[str] = Field(default_factory=list)  # what must be true before acting
    invalidation: Optional[Invalidation] = None  # required for consider_buying / consider_adding
    scenarios: list[Scenario] = Field(default_factory=list)
    costs_and_risks: list[str] = Field(default_factory=list)
    counter_argument: str
    would_change_view: str
    value_or_trap: Optional[str] = None  # for pullbacks: why this is not (or might be) a value trap
    confidence: ConfidenceLabel
    confidence_basis: str
    revision_of: Optional[str] = None  # idea_id this revises
    revision_note: Optional[str] = None
    sources: list[SourceRef] = Field(min_length=1)


class PortfolioCommentary(Strict):
    summary: str
    holding_notes: list[MarketNote] = Field(default_factory=list)  # instrument_key = ticker
    fit_of_ideas: list[str] = Field(default_factory=list)


class CalendarItem(Strict):
    when: str  # ISO date or datetime with timezone
    what: str
    relevance: str
    source: Optional[SourceRef] = None


class SourceConflict(Strict):
    topic: str
    detail: str
    resolution: str


class Editorial(Strict):
    edition_id: str
    headline: str
    dek: str  # one-paragraph standfirst
    tldr: list[str] = Field(default_factory=list, max_length=5)  # "In 30 seconds": the edition in 3-4 lines
    developments: list[Development] = Field(min_length=1, max_length=6)
    market_read: MarketRead
    changes_since_last: list[str] = Field(default_factory=list)
    featured: list[FeaturedStock] = Field(default_factory=list, max_length=6)
    ideas: list[Idea] = Field(default_factory=list, max_length=6)
    no_setup_statement: Optional[str] = None
    portfolio: Optional[PortfolioCommentary] = None
    calendar: list[CalendarItem] = Field(default_factory=list)
    source_conflicts: list[SourceConflict] = Field(default_factory=list)
    research_notes: Optional[str] = None  # limits of today's research, shown in Method


# ---------------------------------------------------------------------------
# Durable history
# ---------------------------------------------------------------------------


class LedgerRevision(Strict):
    edition_id: str
    on: date
    action: ActionType
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    invalidation: Optional[float] = None
    note: Optional[str] = None


class LedgerOutcome(Strict):
    evaluated_on: date
    last_close: Optional[float] = None
    zone_touched_on: Optional[date] = None  # a daily range overlapped the zone; NOT a fill
    invalidation_touched_on: Optional[date] = None
    hypothetical_return_from_zone_mid_pct: Optional[float] = None
    days_open: int = 0
    note: Optional[str] = None


class LedgerEntry(Strict):
    idea_id: str
    symbol: str
    first_published: date
    edition_id: str
    action: ActionType
    horizon_label: str
    horizon_max_days: int
    thesis: str
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    invalidation: Optional[float] = None
    invalidation_meaning: Optional[str] = None
    price_at_publication: Optional[float] = None
    status: Literal["open", "expired", "invalidated", "closed_by_revision"] = "open"
    revisions: list[LedgerRevision] = Field(default_factory=list)
    outcome: Optional[LedgerOutcome] = None


class Ledger(Strict):
    entries: list[LedgerEntry] = Field(default_factory=list)


class RunRecord(Strict):
    edition_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: Literal["running", "succeeded", "partial", "failed", "skipped_closed", "skipped_duplicate"]
    revision: int = 1
    trigger: Literal["scheduled", "manual", "test", "demo"] = "manual"
    problems: list[str] = Field(default_factory=list)
    data_cutoff: Optional[datetime] = None
