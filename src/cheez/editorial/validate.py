"""Deterministic checks on the model-written editorial before anything is rendered.

The language model proposes; this module decides whether a proposal is
publishable. Errors block rendering (the run asks the model to fix them, with a
bounded number of attempts). Warnings are recorded in the run log and shown in
the Method section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from ..analytics.portfolio import holdings_index
from ..analytics.technicals import fact_keys
from ..models import Editorial, Idea, Ledger, PortfolioSnapshot, SessionContext, StockFacts

# Long-only, cash-account actions. Anything that needs a holding is listed here.
NEEDS_HOLDING = {"consider_adding", "hold", "consider_trimming", "consider_exiting"}
NEEDS_LEVELS = {"consider_buying", "consider_adding"}

# Leveraged / inverse products are never proposed. Names are checked as well as tickers.
LEVERAGED_TICKERS = {
    "TQQQ", "SQQQ", "SOXL", "SOXS", "UPRO", "SPXU", "SPXL", "SPXS", "SSO", "SDS", "QLD", "QID",
    "UVXY", "SVXY", "VXX", "UVIX", "SVIX", "TNA", "TZA", "LABU", "LABD", "FAS", "FAZ", "TSLL",
    "TSLQ", "NVDL", "NVDU", "NVDD", "NVDQ", "CONL", "MSTU", "MSTX", "MSTZ", "BITX", "YINN", "YANG",
    "FNGU", "FNGD", "TECL", "TECS", "TMF", "TMV", "BOIL", "KOLD", "UCO", "SCO", "AGQ", "ZSL", "NUGT",
    "DUST", "JNUG", "JDST", "SH", "PSQ", "DOG", "RWM", "TBT", "TBF", "USD", "SMDD", "AMDL", "AAPU",
    "MSFU", "GGLL", "AMZU", "METU", "PLTU", "ETHU", "SBIT",
}
LEVERAGED_NAME = re.compile(r"\b(2x|3x|-1x|-2x|-3x|ultra|ultrapro|inverse|bear|leveraged|daily target)\b", re.I)

FORBIDDEN_PHRASES = [
    r"\bguarantee[sd]?\b", r"\brisk[- ]free\b", r"\bcan(?:no|')?t lose\b", r"\bcertain to\b",
    r"\bwill definitely\b", r"\bsure thing\b", r"\bno[- ]brainer\b", r"\bfree money\b",
    r"\bthe bottom is in\b", r"\bbottom is in\b", r"\bcan(?:no|')?t go (?:any )?lower\b",
    r"\bsafe (?:entry|price|level|stock|buy|bet|investment|haven stock)\b", r"\bguaranteed recovery\b",
    r"\bwill (?:surely )?recover\b",
]
NEGATION = re.compile(r"\b(not|no|never|nor|isn't|is not|aren't|without|cannot|can't)\b[^.;]*$", re.I)
PROBABILITY = re.compile(
    r"(\b\d{1,3}(?:\.\d+)?\s?%\s+(?:chance|probability|likelihood|odds)\b)|(\bprobability of\s+\d)|(\b\d{1,2}\s?(?:/|out of)\s?10\b)",
    re.I,
)
PRECISE_FAIR_VALUE = re.compile(r"\bfair value\b[^.]{0,30}?(?:\$|USD\s?)?\d{1,6}(?:\.\d+)?\b", re.I)
SHARE_COUNT = re.compile(r"\b(?:buy|sell|trim|add|purchase)\s+(?:about\s+)?\d[\d,]*\s+shares?\b", re.I)
DERIVATIVE_ADVICE = re.compile(
    r"\b(?:buy|sell|write|use|consider|own|hold)\b[^.]{0,25}\b(?:call|put)s?(?: options?)?\b"
    r"|\b(?:buy|sell|use|consider)\b[^.]{0,25}\b(?:options|futures contracts?|cfds?|warrants)\b"
    r"|\bsell(?:ing)? short\b|\bshort(?:ing)? (?:the|this|it|shares)\b|\bon margin\b|\bborrow(?:ing)? to (?:buy|invest)\b",
    re.I,
)


@dataclass
class IdeaDerived:
    last_price: Optional[float] = None
    distance_to_zone_pct: Optional[float] = None  # + means price is above the zone
    reward_risk: Optional[float] = None
    reward_risk_basis: Optional[str] = None
    target: Optional[float] = None  # the most conservative upside scenario above the zone midpoint
    downside_to_invalidation_pct: Optional[float] = None
    held: bool = False


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    derived: dict[str, IdeaDerived] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _texts(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """Every string in the editorial, with its path, except URLs."""
    out: list[tuple[str, str]] = []
    if isinstance(obj, str):
        out.append((path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("url",):
                continue
            out.extend(_texts(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_texts(v, f"{path}[{i}]"))
    return out


def _near(level: float, low: float, high: float, tol: float) -> bool:
    return (low - tol) <= level <= (high + tol)


def _check_idea(
    idea: Idea,
    facts: Optional[StockFacts],
    holdings: dict[str, dict],
    portfolio_ok: bool,
    session: SessionContext,
    rep: ValidationReport,
) -> None:
    tag = f"idea {idea.idea_id} ({idea.symbol})"
    sym = idea.symbol.upper()
    der = IdeaDerived(held=sym in holdings)
    rep.derived[idea.idea_id] = der

    if sym in LEVERAGED_TICKERS:
        rep.errors.append(f"{tag}: leveraged or inverse products are out of scope.")
    if facts is None:
        rep.errors.append(f"{tag}: no verified market data for this ticker; verify identity and add it to the research universe.")
        return
    if facts.identity.ambiguous:
        rep.errors.append(f"{tag}: ticker identity is ambiguous ({facts.identity.note}); resolve before publishing.")
    if facts.identity.name and LEVERAGED_NAME.search(facts.identity.name):
        rep.errors.append(f"{tag}: '{facts.identity.name}' looks like a leveraged/inverse product.")

    if idea.action in NEEDS_HOLDING:
        if not portfolio_ok:
            rep.errors.append(
                f"{tag}: '{idea.action}' is personalised but portfolio data is unavailable; use 'watch', 'wait' or 'consider_buying'."
            )
        elif sym not in holdings:
            rep.errors.append(f"{tag}: '{idea.action}' requires a current holding of {sym}, which the portfolio does not show.")
        elif idea.action in ("consider_trimming", "consider_exiting") and holdings[sym]["available"] <= 0:
            rep.errors.append(f"{tag}: no sellable quantity available for {sym} (it may be locked by open orders or unsettled).")

    if not session.is_trading_day and idea.decision_today:
        rep.errors.append(f"{tag}: US markets are closed today; nothing can be a decision for today.")

    last = None
    if facts.last is not None:
        last = facts.last.value
    elif facts.regular_close is not None:
        last = facts.regular_close.value
    der.last_price = last
    t = facts.technicals
    keys = fact_keys(t)
    tol_abs = max((t.atr14 or 0.0), (last or 0.0) * 0.03)

    if idea.action in NEEDS_LEVELS:
        if idea.entry is None or idea.invalidation is None:
            rep.errors.append(f"{tag}: '{idea.action}' needs an entry zone and an invalidation level.")
            return
    if idea.entry is not None:
        e = idea.entry
        if e.low <= 0 or e.high <= 0 or e.low > e.high:
            rep.errors.append(f"{tag}: entry zone {e.low}-{e.high} is not a valid range.")
            return
        if last:
            if e.high > last * 1.10:
                rep.errors.append(f"{tag}: entry zone top {e.high:.2f} is >10% above the last price {last:.2f}; not supported.")
            if e.low < last * 0.55:
                rep.errors.append(f"{tag}: entry zone bottom {e.low:.2f} is >45% below the last price {last:.2f}; too remote to be actionable.")
            if (e.high - e.low) / last > 0.15:
                rep.warnings.append(f"{tag}: entry zone is wider than 15% of price; consider narrowing or explaining.")
            mid = (e.low + e.high) / 2
            der.distance_to_zone_pct = (last / mid - 1) * 100
        if not e.basis:
            rep.errors.append(f"{tag}: entry zone has no cited basis (e.g. sma50, swing_low:YYYY-MM-DD).")
        unknown = [b for b in e.basis if b not in keys and not b.startswith("source:")]
        if unknown:
            rep.errors.append(f"{tag}: entry basis cites unknown facts {unknown}; available: {sorted(keys)[:12]}…")
        cited = [keys[b] for b in e.basis if b in keys and b != "atr14"]
        if cited and not any(_near(v, e.low, e.high, tol_abs) for v in cited):
            rep.errors.append(
                f"{tag}: none of the cited reference levels {[round(v, 2) for v in cited]} lie near the zone {e.low}-{e.high}."
            )
        if len(e.derivation.strip()) < 40:
            rep.errors.append(f"{tag}: entry derivation is too thin to inspect.")
    if idea.invalidation is not None:
        inv = idea.invalidation
        if idea.entry is not None and inv.level >= idea.entry.low:
            rep.errors.append(f"{tag}: invalidation {inv.level} must sit below the entry zone for a long idea.")
        if last and inv.level <= 0:
            rep.errors.append(f"{tag}: invalidation level must be positive.")
        if idea.entry is not None:
            mid = (idea.entry.low + idea.entry.high) / 2
            der.downside_to_invalidation_pct = (inv.level / mid - 1) * 100
        if len(inv.gap_risk.strip()) < 20:
            rep.errors.append(f"{tag}: explain gap risk (a level is not a guaranteed exit price).")

    # Reward/risk only when every input exists and is coherent.
    if idea.entry and idea.invalidation:
        targets = [s.target for s in idea.scenarios if s.target is not None]
        mid = (idea.entry.low + idea.entry.high) / 2
        risk = mid - idea.invalidation.level
        ups = [x for x in targets if x > mid]
        der.target = min(ups) if ups else None
        if any(x <= idea.invalidation.level for x in targets):
            rep.warnings.append(f"{tag}: a scenario target sits at or below invalidation; check scenario labels.")
        if risk > 0 and ups:
            base = der.target  # the most conservative upside scenario
            der.reward_risk = (base - mid) / risk
            der.reward_risk_basis = (
                f"({base:.2f} − {mid:.2f}) ÷ ({mid:.2f} − {idea.invalidation.level:.2f}), using the zone midpoint, "
                "the most conservative upside scenario and the invalidation level; ignores gaps, fees and FX."
            )

    if idea.action in NEEDS_LEVELS and not idea.conditions:
        rep.errors.append(f"{tag}: state the conditions required before acting.")
    if idea.horizon.min_days > idea.horizon.max_days or idea.horizon.min_days < 0:
        rep.errors.append(f"{tag}: horizon range is invalid.")
    if idea.horizon.max_days <= 1 and idea.action in NEEDS_LEVELS:
        rep.errors.append(f"{tag}: Cheez does not publish intraday trades; use a multi-day horizon.")
    if facts.technicals.avg_dollar_volume_20d is not None and facts.technicals.avg_dollar_volume_20d < 5_000_000:
        rep.errors.append(f"{tag}: average daily dollar volume below $5m; too illiquid for this publication.")
    if facts.next_earnings and idea.action in NEEDS_LEVELS:
        days = (facts.next_earnings - session.edition_date).days
        if 0 <= days <= idea.horizon.max_days and not any(
            "earn" in r.lower() for r in idea.costs_and_risks + [idea.catalyst, idea.why_now] + idea.conditions
        ):
            rep.errors.append(f"{tag}: earnings on {facts.next_earnings} fall inside the horizon but are not addressed.")


def validate(
    ed: Editorial,
    *,
    edition_id: str,
    session: SessionContext,
    stocks: dict[str, StockFacts],
    portfolio: Optional[PortfolioSnapshot],
    ledger: Optional[Ledger] = None,
    instrument_keys: Optional[set[str]] = None,
) -> ValidationReport:
    rep = ValidationReport()
    if ed.edition_id != edition_id:
        rep.errors.append(f"edition_id is {ed.edition_id!r}; expected {edition_id!r}.")

    portfolio_ok = bool(portfolio and portfolio.status in ("ok", "partial") and portfolio.accounts)
    holdings = holdings_index(portfolio) if portfolio_ok else {}
    stocks_u = {k.upper(): v for k, v in stocks.items()}

    # Language checks across every field.
    data = ed.model_dump(mode="json")
    for path, text in _texts(data):
        for pat in FORBIDDEN_PHRASES:
            for m in re.finditer(pat, text, re.I):
                before = text[max(0, m.start() - 28): m.start()]
                if NEGATION.search(before):
                    continue  # e.g. "not a guaranteed exit price" is the disclaimer we want
                rep.errors.append(f"{path}: certainty language is not allowed ({m.group(0)!r}).")
                break
        m = PROBABILITY.search(text)
        if m:
            rep.errors.append(f"{path}: invented probabilities or scores are not allowed ({m.group(0)!r}).")
        m = PRECISE_FAIR_VALUE.search(text)
        if m:
            rep.errors.append(f"{path}: precise fair values are not allowed ({m.group(0)!r}).")
        if path.startswith("ideas"):
            m = SHARE_COUNT.search(text)
            if m:
                rep.errors.append(f"{path}: position sizes are not published until risk preferences are configured ({m.group(0)!r}).")
            m = DERIVATIVE_ADVICE.search(text)
            if m:
                rep.errors.append(f"{path}: ideas must be long-only cash equity ({m.group(0)!r}).")

    # Sources must be real links.
    for dev in ed.developments:
        for s in dev.sources:
            if not s.url.startswith(("https://", "http://")):
                rep.errors.append(f"development {dev.title!r}: source url {s.url!r} is not a web link.")

    for f in ed.featured:
        if f.symbol.upper() not in stocks_u:
            rep.errors.append(f"featured {f.symbol}: no verified market data; add it to the research universe.")
        elif stocks_u[f.symbol.upper()].identity.ambiguous:
            rep.errors.append(f"featured {f.symbol}: ambiguous identity ({stocks_u[f.symbol.upper()].identity.note}).")
        for rt in f.read_throughs:
            if rt.label == "established" and not rt.sources:
                rep.errors.append(f"featured {f.symbol} → {rt.symbol}: an 'established' link needs a source.")

    seen_ids: set[str] = set()
    ledger_ids = {e.idea_id for e in (ledger.entries if ledger else [])}
    for idea in ed.ideas:
        if idea.idea_id in seen_ids:
            rep.errors.append(f"duplicate idea_id {idea.idea_id}.")
        seen_ids.add(idea.idea_id)
        if idea.revision_of and idea.revision_of not in ledger_ids:
            rep.errors.append(f"idea {idea.idea_id}: revision_of {idea.revision_of} is not in the ledger.")
        _check_idea(idea, stocks_u.get(idea.symbol.upper()), holdings, portfolio_ok, session, rep)

    if not ed.ideas and not ed.no_setup_statement:
        rep.errors.append("no ideas were published; say plainly that there is no compelling setup (no_setup_statement).")
    if ed.portfolio is not None and not portfolio_ok and ed.portfolio.holding_notes:
        rep.errors.append("portfolio commentary references holdings, but no portfolio data is available.")
    if instrument_keys is not None:
        for n in ed.market_read.notes:
            if n.instrument_key not in instrument_keys:
                rep.warnings.append(f"market note refers to unknown instrument {n.instrument_key!r}.")
    if not session.is_trading_day and ed.ideas:
        rep.warnings.append("ideas published on a closed-market day; they are labelled as watch items.")
    return rep
