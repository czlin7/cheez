"""Read-only Longbridge snapshot.

Authentication is OAuth 2.0 only. Cheez refuses the legacy App Key / App Secret /
Access Token because, per Longbridge's documentation, anyone holding that token
"can trade your account", and it has no scope controls.

The OAuth token must have been granted ``account.read`` (and optionally
``trade.read``) and must NOT carry ``trade.write`` or ``watchlist``. Cheez checks
the scopes it can see in the token before connecting and fails closed when they
cannot be established (see ``check_boundary``).

The SDK runs in a child process with a hard timeout: it holds the GIL during
calls and, if a token cannot be refreshed, would otherwise try to start an
interactive browser login and wait forever.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional

from ..models import (
    Account,
    CashFlow,
    CashLine,
    Coverage,
    Execution,
    OpenOrder,
    PortfolioSnapshot,
    Position,
)
from .readonly import QUOTE_READ_ALLOW, TRADE_READ_ALLOW, ReadOnlyProxy, SafeHttpGet

UTC = timezone.utc
TOKEN_ENV = "CHEEZ_LONGBRIDGE_OAUTH"  # the JSON token file written by `longbridge auth login`
SCOPES_ENV = "CHEEZ_LONGBRIDGE_SCOPES"  # owner's attestation when the token does not reveal its scopes
LEGACY_ENV = (
    "LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN",
    "LONGPORT_APP_KEY", "LONGPORT_APP_SECRET", "LONGPORT_ACCESS_TOKEN",
)
# Scope ids published in https://open.longbridge.com/docs/getting-started.md (global host).
SCOPE_IDS = {"4": "watchlist", "6": "account.read", "10": "trade.read", "11": "trade.write"}
ALLOWED_SCOPES = {"account.read", "trade.read"}
FORBIDDEN_SCOPES = {"trade.write", "watchlist"}
CHILD_TIMEOUT_S = 150
# Explicit endpoints: the SDK otherwise also honours LONGBRIDGE_*_URL variables and a
# .env file in the working directory, either of which could redirect the token.
HTTP_URL = "https://openapi.longbridge.com"
QUOTE_WS_URL = "wss://openapi-quote.longbridge.com/v2"
TRADE_WS_URL = "wss://openapi-trade.longbridge.com/v2"
HISTORY_DAYS = 365
OPEN_STATUSES = {
    "NotReported", "ReplacedNotReported", "ProtectedNotReported", "VarietiesNotReported", "DelayedNotReported",
    "WaitToNew", "New", "WaitToReplace", "PendingReplace", "Replaced", "PartialFilled", "WaitToCancel", "PendingCancel",
}


# ---------------------------------------------------------------------------
# Credential and boundary checks (pure; no network)
# ---------------------------------------------------------------------------


@dataclass
class BoundaryCheck:
    ok: bool
    reason: str
    scopes: Optional[set[str]] = None
    scope_source: Optional[str] = None
    expires_at: Optional[datetime] = None
    warnings: list[str] = field(default_factory=list)


def load_token(env: Optional[dict] = None) -> Optional[dict]:
    env = env if env is not None else dict(os.environ)
    raw = env.get(TOKEN_ENV)
    if not raw:
        return None
    try:
        tok = json.loads(raw)
    except json.JSONDecodeError:
        try:
            tok = json.loads(base64.b64decode(raw).decode())
        except Exception:
            raise ValueError(f"{TOKEN_ENV} is not valid JSON (or base64 JSON)")
    if not isinstance(tok, dict):
        raise ValueError(f"{TOKEN_ENV} must be a JSON object")
    for k in ("client_id", "access_token", "refresh_token"):
        if not isinstance(tok.get(k), str) or not tok.get(k):
            raise ValueError(f"{TOKEN_ENV} is missing '{k}'")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,128}", tok["client_id"]) or tok["client_id"] in (".", ".."):
        raise ValueError(f"{TOKEN_ENV} has an invalid client_id")
    return tok


def _jwt_claims(token: str) -> Optional[dict]:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        pad = "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(parts[1] + pad))
    except Exception:
        return None


def token_scopes(tok: dict) -> tuple[Optional[set[str]], Optional[str]]:
    """Scopes visible in the token itself, normalised to scope keys."""
    candidates: list[Any] = []
    if "scope" in tok:
        candidates.append(tok["scope"])
    claims = _jwt_claims(tok.get("access_token", ""))
    if claims:
        for k in ("scope", "scp", "scopes"):
            if k in claims:
                candidates.append(claims[k])
    found: list[set[str]] = []
    for c in candidates:
        items: Iterable[str]
        if isinstance(c, str):
            items = c.replace(",", " ").split()
        elif isinstance(c, list):
            items = [str(x) for x in c]
        else:
            continue
        found.append({SCOPE_IDS.get(str(i), str(i)) for i in items})
    if not found:
        return None, None
    # Every place the token states its scopes must agree; the union is what is checked,
    # so a hand-edited "scope" field cannot hide a broader grant inside the JWT.
    union = set().union(*found)
    if any(f != found[0] for f in found):
        union.add("conflicting-scope-claims")
    return union, "token"


def _expiry(tok: dict) -> Optional[datetime]:
    v = tok.get("expires_at")
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)) or str(v).isdigit():
            return datetime.fromtimestamp(int(v), tz=UTC)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return None


def check_boundary(env: Optional[dict] = None, now: Optional[datetime] = None) -> BoundaryCheck:
    env = env if env is not None else dict(os.environ)
    now = now or datetime.now(tz=UTC)
    legacy = [k for k in LEGACY_ENV if env.get(k)]
    if legacy:
        return BoundaryCheck(False, "Legacy Longbridge API-key credentials are set (" + ", ".join(legacy) + "). "
                             "They carry trading permission and cannot be scoped, so Cheez will not use any brokerage "
                             "connection until they are removed from the environment.")
    try:
        tok = load_token(env)
    except ValueError as e:
        return BoundaryCheck(False, str(e))
    if tok is None:
        return BoundaryCheck(False, "No Longbridge OAuth token is configured.")
    exp = _expiry(tok)
    scopes, source = token_scopes(tok)
    if scopes is None:
        attested = {s.strip() for s in env.get(SCOPES_ENV, "").split(",") if s.strip()}
        if not attested:
            return BoundaryCheck(False, "The Longbridge token does not reveal its scopes, and the owner has not recorded "
                                 f"which scopes were granted ({SCOPES_ENV}). Cheez fails closed rather than assume the "
                                 "token is read-only.", expires_at=exp)
        scopes, source = attested, "owner_attestation"
    bad = scopes & FORBIDDEN_SCOPES
    if bad:
        return BoundaryCheck(False, f"The Longbridge token carries {', '.join(sorted(bad))}, which can change the account. "
                             "Re-authorise with account.read and trade.read only.", scopes, source, exp)
    unknown = scopes - ALLOWED_SCOPES
    if unknown:
        return BoundaryCheck(False, f"The Longbridge token carries unrecognised scopes {sorted(unknown)}; "
                             "Cheez only accepts account.read and trade.read.", scopes, source, exp)
    if "account.read" not in scopes:
        return BoundaryCheck(False, "The Longbridge token lacks account.read, so holdings cannot be read.", scopes, source, exp)
    chk = BoundaryCheck(True, "Read-only scopes confirmed" + (" by owner attestation" if source == "owner_attestation" else ""),
                        scopes, source, exp)
    if exp is not None:
        left = exp - now
        if left < timedelta(0):
            chk.warnings.append("The Longbridge access token has expired; Cheez will try a refresh.")
        elif left < timedelta(days=7):
            chk.warnings.append(f"The Longbridge authorisation expires on {exp:%d %b %Y}; re-authorise soon.")
    if "trade.read" not in scopes:
        chk.warnings.append("trade.read was not granted: open orders and trade history are unavailable.")
    return chk


# ---------------------------------------------------------------------------
# Normalisation (pure; duck-typed over SDK objects so it can be tested offline)
# ---------------------------------------------------------------------------


def _f(x: Any) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(Decimal(str(x)))
    except Exception:
        return None


def _utc(dt: Any) -> Optional[datetime]:
    """SDK datetimes come back naive in the process timezone; Cheez runs the
    child with TZ=UTC, so naive values are UTC."""
    if dt is None:
        return None
    if isinstance(dt, (int, float)):
        return datetime.fromtimestamp(dt, tz=UTC)
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return None


def _enum_name(x: Any) -> str:
    s = str(x)
    return s.split(".")[-1]


def _hash(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def plain_ticker(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith(".US"):
        return s[:-3].lstrip(".")
    return s


FLOW_RULES = [
    ("deposit", ("deposit", "fund in", "cash in", "入金", "存入")),
    ("withdrawal", ("withdraw", "fund out", "出金", "提取")),
    ("dividend", ("dividend", "派息", "股息")),
    ("fee", ("fee", "commission", "charge", "tax", "费")),
    ("interest", ("interest", "利息")),
    ("fx", ("exchange", "fx", "currency conversion", "换汇", "兑换")),
    ("trade", ("buy", "sell", "contract", "settle", "买", "卖")),
    ("corporate_action", ("split", "bonus", "rights", "merger", "spin", "corporate")),
]


def classify_flow(name: str) -> str:
    n = (name or "").lower()
    for kind, keys in FLOW_RULES:
        if any(k in n for k in keys):
            return kind
    return "other"


def normalise_ap(balances: list, positions_resp: Any, orders: list, executions: list, flows: list,
                 quotes: dict, hist_from: datetime, now: datetime, trade_read: bool) -> list[Account]:
    accounts: list[Account] = []
    bal = balances[0] if balances else None
    channels = getattr(positions_resp, "channels", []) or []
    if not channels:
        channels = [type("C", (), {"account_channel": "lb", "positions": []})()]
    for idx, ch in enumerate(channels):
        acct = Account(label=f"Account {idx + 1}" if len(channels) > 1 else "Longbridge account",
                       account_channel=getattr(ch, "account_channel", None))
        if bal is not None and idx == 0:
            acct.base_currency = getattr(bal, "currency", None)
            acct.net_assets = _f(getattr(bal, "net_assets", None))
            acct.total_cash = _f(getattr(bal, "total_cash", None))
            mx, rem = _f(getattr(bal, "max_finance_amount", None)), _f(getattr(bal, "remaining_finance_amount", None))
            notes = []
            if mx is not None and rem is not None and mx - rem > 0.005:
                notes.append(f"Financing in use: about {mx - rem:,.2f} {acct.base_currency}.")
            risk = getattr(bal, "risk_level", None)
            if risk is not None and int(risk) >= 2:
                notes.append(f"Broker risk level {int(risk)} (2 = early warning, 3 = danger).")
            if (_f(getattr(bal, "margin_call", None)) or 0) > 0:
                notes.append("The broker reports a margin call amount.")
            notes.append("Buying power reported by the broker includes margin and is not treated as cash.")
            acct.margin_or_financing_note = " ".join(notes)
            for ci in getattr(bal, "cash_infos", []) or []:
                avail = _f(getattr(ci, "available_cash", None))
                wd = _f(getattr(ci, "withdraw_cash", None))
                acct.cash.append(CashLine(
                    currency=getattr(ci, "currency", "?"),
                    cash_balance=avail,
                    available=max(wd, 0.0) if wd is not None else None,
                    withdrawable=wd,
                    frozen=_f(getattr(ci, "frozen_cash", None)),
                    settling=_f(getattr(ci, "settling_cash", None)),
                ))
        for p in getattr(ch, "positions", []) or []:
            sym = getattr(p, "symbol", "")
            q = quotes.get(sym)
            qty = _f(getattr(p, "quantity", None)) or 0.0
            if qty <= 0:
                continue  # long-only view; a negative/zero line is not a holding Cheez reasons about
            cost = _f(getattr(p, "cost_price", None))
            pos = Position(
                symbol=sym, ticker=plain_ticker(sym), name=getattr(p, "symbol_name", None),
                market=_enum_name(getattr(p, "market", "")) or None, currency=getattr(p, "currency", "USD"),
                quantity=qty, available_quantity=max(_f(getattr(p, "available_quantity", None)) or 0.0, 0.0),
                cost_price=cost if cost and cost > 0 else None,
                cost_price_note="Broker cost price (average or diluted, per your app setting).",
            )
            if q:
                pos.last_price, pos.last_price_as_of, pos.last_price_session = q["price"], q["as_of"], q["session"]
                pos.market_value = pos.last_price * qty
                pos.lot_size = q.get("lot_size")
            acct.positions.append(pos)
        accounts.append(acct)

    main = accounts[0]
    if trade_read:
        for o in orders:
            st = _enum_name(getattr(o, "status", ""))
            if st not in OPEN_STATUSES:
                continue
            side = _enum_name(getattr(o, "side", "")).lower()
            main.open_orders.append(OpenOrder(
                symbol=plain_ticker(getattr(o, "symbol", "")), side="sell" if side == "sell" else "buy",
                quantity=_f(getattr(o, "quantity", None)) or 0.0,
                executed_quantity=_f(getattr(o, "executed_quantity", None)) or 0.0,
                price=_f(getattr(o, "price", None)), order_type=_enum_name(getattr(o, "order_type", "")),
                status=st, submitted_at=_utc(getattr(o, "submitted_at", None)), currency=getattr(o, "currency", None),
            ))
        seen: set[str] = set()
        for e in executions:
            tid = str(getattr(e, "trade_id", ""))
            if not tid or tid in seen:
                continue
            seen.add(tid)
            side = _enum_name(getattr(e, "side", "")).lower()
            main.executions.append(Execution(
                trade_id=_hash("lb", tid), symbol=plain_ticker(getattr(e, "symbol", "")),
                side="sell" if side == "sell" else "buy" if side == "buy" else None,
                quantity=_f(getattr(e, "quantity", None)) or 0.0, price=_f(getattr(e, "price", None)) or 0.0,
                executed_at=_utc(getattr(e, "trade_done_at", None)) or now,
            ))
        main.executions_coverage = Coverage(
            requested_from=hist_from.date(), requested_to=now.date(),
            retrieved_from=min((x.executed_at for x in main.executions), default=None).date() if main.executions else hist_from.date(),
            retrieved_to=now.date(), records=len(main.executions), complete=False,
            note="Covers the window requested from the broker API; earlier trades are not included.",
        )
    else:
        main.executions_coverage = Coverage(note="trade.read not granted; no order or trade history read.")
    seen_f: set[str] = set()
    for fl in flows:
        at = _utc(getattr(fl, "business_time", None)) or now
        name = getattr(fl, "transaction_flow_name", "") or ""
        amt = _f(getattr(fl, "balance", None)) or 0.0
        fid = _hash(name, at.isoformat(), amt, getattr(fl, "currency", ""), getattr(fl, "symbol", ""))
        if fid in seen_f:
            continue
        seen_f.add(fid)
        main.cash_flows.append(CashFlow(flow_id=fid, kind=classify_flow(name), currency=getattr(fl, "currency", "?"),
                                        amount=amt, at=at, symbol=getattr(fl, "symbol", None) or None,
                                        description=name[:60]))
    main.cash_flows_coverage = Coverage(requested_from=hist_from.date(), requested_to=now.date(),
                                        retrieved_from=hist_from.date(), retrieved_to=now.date(),
                                        records=len(main.cash_flows), complete=False,
                                        note="Flow names are classified by keyword; unclassified items show as 'other'.")
    return accounts


def normalise_us(overview: Any, cash: Any, orders_json: Optional[str], now: datetime) -> list[Account]:
    acct = Account(label="Longbridge US account", base_currency=getattr(overview, "currency", None) or "USD")
    for c in getattr(cash, "cash_list", []) or []:
        wd = _f(getattr(c, "withdraw_cash", None))
        acct.cash.append(CashLine(currency=getattr(c, "currency", "USD"), cash_balance=_f(getattr(c, "total_amount", None)),
                                  available=max(_f(getattr(c, "available_cash", None)) or 0.0, 0.0), withdrawable=wd,
                                  frozen=_f(getattr(c, "frozen_cash", None)), settling=None))
    ms = getattr(cash, "margin_status", None)
    if ms is not None:
        acct.net_assets = _f(getattr(ms, "nlv", None))
    acct.margin_or_financing_note = "Buying power reported by the broker includes margin and is not treated as cash."
    for s in getattr(overview, "stock_list", []) or []:
        qty = _f(getattr(s, "quantity", None)) or 0.0
        if qty <= 0 or str(getattr(s, "position_side", "")).lower().startswith("short"):
            continue
        px = _f(getattr(s, "last_done", None)) or _f(getattr(s, "market_price", None))
        acct.positions.append(Position(
            symbol=getattr(s, "full_symbol", None) or f"{getattr(s, 'symbol', '')}.US", ticker=str(getattr(s, "symbol", "")).upper(),
            name=getattr(s, "name", None), market=getattr(s, "market", None) or "US", currency=getattr(s, "currency", "USD"),
            quantity=qty, cost_price=_f(getattr(s, "average_cost", None)) or None,
            cost_price_note="Broker average cost.", last_price=px,
            last_price_as_of=_utc(getattr(overview, "asset_timestamp", None)) if getattr(overview, "asset_timestamp", None) else now,
            last_price_session="unknown", market_value=(px * qty) if px else None,
            sector=getattr(s, "industry_name", None) or None,
        ))
    acct.executions_coverage = Coverage(note="US account trade history is not yet read by Cheez.")
    acct.cash_flows_coverage = Coverage(note="US account transaction history is not yet read by Cheez.")
    _ = orders_json
    return [acct]


# ---------------------------------------------------------------------------
# Child process: the only place the SDK is imported
# ---------------------------------------------------------------------------


def _quote_map(qctx: Any, symbols: list[str]) -> dict:
    out: dict = {}
    if not symbols:
        return out
    for q in qctx.quote(symbols[:500]):
        best = (_f(q.last_done), _utc(q.timestamp), "regular_close")
        for attr, label in (("pre_market_quote", "pre_market"), ("post_market_quote", "post_market")):
            pq = getattr(q, attr, None)
            if pq is not None and _f(pq.last_done) and _utc(pq.timestamp) and best[1] and _utc(pq.timestamp) > best[1]:
                best = (_f(pq.last_done), _utc(pq.timestamp), label)
        if best[0]:
            out[q.symbol] = {"price": best[0], "as_of": best[1], "session": best[2]}
    try:
        for s in qctx.static_info(symbols[:500]):
            if s.symbol in out:
                out[s.symbol]["lot_size"] = int(getattr(s, "lot_size", 0) or 0) or None
    except Exception:
        pass
    return out


def _positions_from_raw(data: Any) -> Any:
    """Lenient parse of GET /v1/asset/stock when the typed SDK rejects the payload
    (it fails if any position lacks cost_price). Missing cost means unknown, never 0."""
    from types import SimpleNamespace as NS

    if isinstance(data, str):
        data = json.loads(data)
    lst = (data or {}).get("list") or (data or {}).get("channels") or []
    chans = []
    for ch in lst:
        items = ch.get("stock_info") or ch.get("positions") or []
        chans.append(NS(account_channel=ch.get("account_channel"), positions=[
            NS(symbol=i.get("symbol", ""), symbol_name=i.get("symbol_name"), quantity=i.get("quantity"),
               available_quantity=i.get("available_quantity"), currency=i.get("currency", "USD"),
               cost_price=i.get("cost_price") or None, market=i.get("market"))
            for i in items]))
    return NS(channels=chans)


def _windows(start: datetime, end: datetime, days: int = 89) -> list[tuple[datetime, datetime]]:
    out = []
    a = start
    while a < end:
        b = min(a + timedelta(days=days), end)
        out.append((a, b))
        a = b
    return out


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


def child_main() -> int:  # pragma: no cover - exercised via subprocess in tests with a mock server
    os.environ["TZ"] = "UTC"
    try:
        time.tzset()
    except AttributeError:
        pass
    from longbridge.openapi import Config, Language, OAuthBuilder, QuoteContext, QuoteTransport, TradeContext
    from longbridge.openapi import HttpClient as _RawHttp  # wrapped immediately in SafeHttpGet (GET-only allowlist)

    now = datetime.now(tz=UTC).replace(microsecond=0)
    trade_read = os.environ.get("CHEEZ_LB_TRADE_READ", "1") == "1"
    mock_url = os.environ.get("CHEEZ_LB_MOCK_URL")
    if mock_url:
        if not mock_url.startswith("http://127.0.0.1:"):
            raise SystemExit("mock url must be local")
        cfg = Config.from_apikey("test", "test", "test", http_url=mock_url, quote_ws_url="ws://127.0.0.1:9",
                                 trade_ws_url="ws://127.0.0.1:9", enable_print_quote_packages=False)
        http = SafeHttpGet(_RawHttp.from_apikey("test", "test", "test", http_url=mock_url))
    else:
        tok = load_token()
        assert tok is not None
        home = os.environ["CHEEZ_LB_HOME"]  # created, and always deleted, by the parent process
        os.environ["HOME"] = home
        tdir = os.path.join(home, ".longbridge", "openapi", "tokens")
        os.makedirs(tdir, mode=0o700)
        path = os.path.join(tdir, tok["client_id"])
        with open(path, "w") as fh:
            json.dump({k: tok[k] for k in ("client_id", "access_token", "refresh_token", "expires_at") if k in tok}, fh)
        os.chmod(path, 0o600)

        def no_browser(url: str) -> None:
            raise RuntimeError("REAUTH_REQUIRED")

        import asyncio

        async def _build():
            # build_async under a timeout: if the cached token cannot be used or
            # refreshed, the SDK would otherwise wait forever for a browser login.
            return await asyncio.wait_for(OAuthBuilder(tok["client_id"]).build_async(no_browser), timeout=45)

        try:
            oauth = asyncio.run(_build())
        except (asyncio.TimeoutError, TimeoutError):
            raise RuntimeError("REAUTH_REQUIRED")
        cfg = Config.from_oauth(oauth, http_url=HTTP_URL, quote_ws_url=QUOTE_WS_URL, trade_ws_url=TRADE_WS_URL,
                                language=Language.EN, enable_print_quote_packages=False,
                                quote_transport=QuoteTransport.Http)
        http = SafeHttpGet(_RawHttp.from_oauth(oauth, http_url=HTTP_URL))
        try:
            with open(path) as fh:
                after = json.load(fh)
            if after.get("refresh_token") != tok.get("refresh_token"):
                print(json.dumps({"event": "token_rotated", "expires_at": after.get("expires_at")}), file=sys.stderr)
        except Exception:
            pass

    trade = ReadOnlyProxy(TradeContext(cfg), TRADE_READ_ALLOW, "TradeContext")
    quote = ReadOnlyProxy(QuoteContext(cfg), QUOTE_READ_ALLOW, "QuoteContext")
    hist_from = now - timedelta(days=HISTORY_DAYS)
    region = "ap"
    try:
        balances = trade.account_balance()
    except Exception as e:
        if "region" in str(e).lower() or "dc" in str(e).lower():
            region = "us"
            balances = []
        else:
            raise
    if region == "ap":
        time.sleep(0.2)
        try:
            positions = trade.stock_positions()
        except Exception as e:
            if "deserialize" not in str(e):
                raise
            positions = _positions_from_raw(http.get("/v1/asset/stock"))
        syms = [p.symbol for ch in positions.channels for p in ch.positions]
        try:
            quotes = _quote_map(quote, syms)
        except Exception as e:  # prices can be filled from the public feed by the parent
            quotes = {}
            print(json.dumps({"event": "quote_failed", "error": type(e).__name__}), file=sys.stderr)
        orders, execs, flows = [], [], []
        if trade_read:
            time.sleep(0.2)
            orders = trade.today_orders()
            time.sleep(0.2)
            execs = list(trade.today_executions())
            for a, b in _windows(hist_from, now - timedelta(days=1)):
                time.sleep(0.25)
                execs.extend(trade.history_executions(start_at=_naive(a), end_at=_naive(b)))
        for a, b in _windows(hist_from, now):
            page = 1
            while page <= 20:
                time.sleep(0.25)
                batch = trade.cash_flow(start_at=_naive(a), end_at=_naive(b), page=page, size=500)
                flows.extend(batch)
                if len(batch) < 500:
                    break
                page += 1
        accounts = normalise_ap(balances, positions, orders, execs, flows, quotes, hist_from, now, trade_read)
    else:
        overview = trade.us_asset_overview()
        cash = trade.us_cash_and_buy_power()
        accounts = normalise_us(overview, cash, None, now)
    snap = PortfolioSnapshot(status="ok", provider="longbridge", retrieved_at=now, as_of=now, accounts=accounts,
                             messages=[f"Longbridge {region.upper()} data centre account."])
    sys.stdout.write(snap.model_dump_json())
    return 0


# ---------------------------------------------------------------------------
# Parent-side entry point
# ---------------------------------------------------------------------------


def fetch_snapshot(now: datetime, env: Optional[dict] = None, timeout: int = CHILD_TIMEOUT_S) -> PortfolioSnapshot:
    env = dict(env if env is not None else os.environ)
    if not env.get("CHEEZ_LB_MOCK_URL"):
        try:
            chk = check_boundary(env, now)
        except Exception as e:  # never let a malformed credential abort the whole edition
            return PortfolioSnapshot(status="error", messages=[f"The Longbridge credential could not be read ({type(e).__name__})."])
        if not chk.ok:
            status = "unconfigured" if "No Longbridge OAuth token" in chk.reason else "error"
            return PortfolioSnapshot(status=status, messages=[chk.reason])
        env["CHEEZ_LB_TRADE_READ"] = "1" if chk.scopes and "trade.read" in chk.scopes else "0"
        warnings = chk.warnings
    else:
        warnings = ["Mock brokerage data (test)."]
    env["TZ"] = "UTC"
    for k in list(env):  # no SDK overrides from the environment (log paths, alternative endpoints)
        if k.startswith(("LONGBRIDGE_", "LONGPORT_")):
            env.pop(k)
    src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    workdir = tempfile.mkdtemp(prefix="cheez-lb-cwd-")  # empty: the SDK reads .env from the working directory
    home = tempfile.mkdtemp(prefix="cheez-lb-home-")  # the child's private HOME for the token copy
    env["CHEEZ_LB_HOME"] = home
    try:
        proc = subprocess.run([sys.executable, "-m", "cheez.brokerage.longbridge"], env=env, capture_output=True,
                              text=True, timeout=timeout, cwd=workdir)
    except subprocess.TimeoutExpired:
        return PortfolioSnapshot(status="error", messages=[f"Longbridge did not respond within {timeout} seconds."])
    finally:
        # Deleted here, in the parent, so the token copy is removed even if the child was killed.
        shutil.rmtree(workdir, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
    if proc.returncode != 0:
        err = proc.stderr or ""
        if "REAUTH_REQUIRED" in err:
            msg = "Longbridge authorisation has expired and could not be refreshed. Re-authorise (see docs/SETUP.md)."
        elif "403308" in err:
            msg = "Longbridge refused a read (error 403308: missing scope, or no permission for that market)."
        else:
            kind = re.findall(r"^([A-Za-z_][\w.]*(?:Error|Exception))\b", err, re.M)
            msg = f"Longbridge snapshot failed ({kind[-1] if kind else 'unknown error'}). Details are not published."
        return PortfolioSnapshot(status="error", messages=[msg])
    try:
        snap = PortfolioSnapshot.model_validate_json(proc.stdout)
    except Exception:
        return PortfolioSnapshot(status="error", messages=["Longbridge returned data Cheez could not read."])
    snap.messages.extend(warnings)
    if "token_rotated" in (proc.stderr or ""):
        snap.messages.append("Longbridge issued a new refresh token during this run. Cheez cannot save it back to the "
                             "environment; if tomorrow's run reports an authorisation error, re-authorise.")
    return snap


def _redact(s: str) -> str:
    return re.sub(r"[A-Za-z0-9_\-.%+/=]{16,}", "[redacted]", s)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(child_main())
