"""The client-side read-only boundary for Longbridge.

This is the second of three layers (see docs/SECURITY.md):

1. Server-side: an OAuth token granted only ``account.read`` and ``trade.read``.
   Without ``trade.write`` Longbridge rejects order placement, replacement and
   cancellation (error 403308) whatever the client does.
2. Client-side (this module): Cheez only ever touches SDK objects through
   ``ReadOnlyProxy``, which exposes an explicit allowlist of read methods and
   raises on everything else. Contexts that can mutate account state (alerts,
   sharelists, community posts, DCA, grid, fund orders, agent conversations) and
   the raw ``HttpClient`` are never constructed. A test scans the whole repository
   for references to mutating method names.
3. Harness-side: in a session that holds the Longbridge credential, a Claude Code
   PreToolUse hook only lets the agent run ``cheez`` commands, so the model
   cannot write or run its own brokerage code.
"""

from __future__ import annotations

from typing import Any

# Read methods Cheez is allowed to call, per SDK context. Keep this list short:
# add a method only when the briefing needs it and it is documented as read-only.
TRADE_READ_ALLOW = frozenset({
    "account_balance",
    "stock_positions",
    "fund_positions",
    "today_orders",
    "history_orders",
    "today_executions",
    "history_executions",
    "cash_flow",
    # US data-centre accounts expose read-only equivalents under a us_ prefix.
    "us_asset_overview",
    "us_cash_and_buy_power",
    "us_available_holding",
    "us_query_orders",
    "us_transaction_history",
    "us_exchange_rates",
})

QUOTE_READ_ALLOW = frozenset({
    "quote",
    "static_info",
    "history_candlesticks_by_date",
    "candlesticks",
    "trading_days",
    "trading_session",
    "quote_level",
    "quote_package_details",
})

# Names that must never be called. Used by the proxy for a clearer error and by
# tests/test_readonly_boundary.py to scan the repository.
FORBIDDEN_METHODS = frozenset({
    "submit_order", "submit_multileg", "replace_order", "cancel_order",
    "create_watchlist_group", "update_watchlist_group", "delete_watchlist_group", "update_pinned",
    "refresh_access_token", "refresh_access_token_async",
    "create_topic", "create_topic_reply",
    "set_reminder", "conversation", "continue_conversation",
})
# Whole SDK classes Cheez never constructs.
FORBIDDEN_CLASSES = frozenset({
    "HttpClient", "AlertContext", "SharelistContext", "DCAContext", "GridContext",
    "FundContext", "AgentContext", "ContentContext",
    "AsyncHttpClient", "AsyncAlertContext", "AsyncSharelistContext", "AsyncDCAContext",
    "AsyncGridContext", "AsyncFundContext", "AsyncAgentContext", "AsyncContentContext",
})


class ReadOnlyViolation(PermissionError):
    pass


class ReadOnlyProxy:
    """Wraps an SDK context and exposes only allow-listed methods.

    The wrapped object is held in a closure, not an attribute, and allowed
    methods are returned as plain functions (no ``__self__``), so the raw SDK
    context cannot be reached through the proxy."""

    __slots__ = ("_call", "_allow", "_name")

    def __init__(self, target: Any, allow: frozenset[str], name: str):
        def call(item: str) -> Any:
            fn = getattr(target, item)

            def method(*args: Any, **kwargs: Any) -> Any:
                return fn(*args, **kwargs)

            method.__name__ = item
            return method

        object.__setattr__(self, "_call", call)
        object.__setattr__(self, "_allow", allow)
        object.__setattr__(self, "_name", name)

    def __getattribute__(self, item: str) -> Any:
        if item.startswith("__") and item in ("__class__", "__dir__", "__repr__", "__setattr__"):
            return object.__getattribute__(self, item)
        allow = object.__getattribute__(self, "_allow")
        name = object.__getattribute__(self, "_name")
        if item in allow:
            return object.__getattribute__(self, "_call")(item)
        raise ReadOnlyViolation(f"{name}.{item} is not on Cheez's read-only allowlist")

    def __setattr__(self, key: str, value: Any) -> None:
        raise ReadOnlyViolation("read-only proxy cannot be modified")

    def __dir__(self) -> list[str]:
        return sorted(object.__getattribute__(self, "_allow"))


# Raw HTTP is used only as a fallback when the typed SDK cannot parse a read
# response (e.g. a position without a cost price). Only GET, only these paths.
HTTP_GET_ALLOW = frozenset({
    "/v1/asset/account",
    "/v1/asset/stock",
    "/v1/asset/fund",
    "/v1/asset/cashflow",
    "/v1/trade/order/today",
    "/v1/trade/execution/today",
    "/v1/trade/execution/history",
})


class SafeHttpGet:
    """GET-only wrapper over the SDK's raw HTTP client with a path allowlist."""

    __slots__ = ("_client",)

    def __init__(self, client: Any):
        object.__setattr__(self, "_client", client)

    def get(self, path: str) -> Any:
        base = path.split("?", 1)[0]
        if base not in HTTP_GET_ALLOW:
            raise ReadOnlyViolation(f"GET {base} is not on Cheez's read-only allowlist")
        return self._client.request("get", path)

    def __getattr__(self, item: str) -> Any:
        raise ReadOnlyViolation(f"SafeHttpGet.{item} is not available; only get() is allowed")

    def __setattr__(self, key: str, value: Any) -> None:
        raise ReadOnlyViolation("read-only wrapper cannot be modified")
