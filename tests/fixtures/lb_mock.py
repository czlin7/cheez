"""Local mock of Longbridge HTTP endpoints (read-only GETs) to observe SDK parsing/pagination.
Mutating paths respond 403 and are logged so we can prove nothing mutating is called."""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

LOG = []
DEBUG = False

def env(data):
    return {"code": 0, "message": "success", "data": data}

ACCOUNT = {"list": [{
    "total_cash": "1759070010.72", "max_finance_amount": "977582000", "remaining_finance_amount": "0",
    "risk_level": "1", "margin_call": "2598051051.50", "currency": "HKD", "net_assets": "24145.90",
    "init_margin": "1540.09", "maintenance_margin": "1540.09", "buy_power": "1759070.12",
    "cash_infos": [
        {"withdraw_cash": "97592.30", "available_cash": "195902464.37", "frozen_cash": "11579339.13", "settling_cash": "207288537.81", "currency": "HKD"},
        {"withdraw_cash": "-38665.68", "available_cash": "-38665.68", "frozen_cash": "28723.76", "settling_cash": "-276806.51", "currency": "USD"}],
    "frozen_transaction_fees": [{"currency": "USD", "frozen_transaction_fee": "6.51"}]}]}

STOCK = {"list": [{"account_channel": "lb", "stock_info": [
    {"symbol": "700.HK", "symbol_name": "TENCENT", "currency": "HKD", "quantity": "650", "market": "HK", "available_quantity": "-450", "cost_price": "457.53", "init_quantity": "214"},
    {"symbol": "TCEHY.US", "symbol_name": "Tencent (ADR)", "currency": "USD", "market": "US", "quantity": "10", "available_quantity": "10", "init_quantity": "18"}]}]}

FUND = {"list": [{"account_channel": "lb", "fund_info": [
    {"counter_id": "UT/FD/HK0000447943", "symbol_name": "X FUND", "currency": "USD", "holding_units": "5.000",
     "current_net_asset_value": "0", "cost_net_asset_value": "0.00", "net_asset_value_day": "1649865600"}]}]}

def order(i, status="FilledStatus"):
    return {"order_id": str(700000000000000000 + i), "status": status, "stock_name": "Apple", "quantity": "10",
            "executed_quantity": "10", "price": "100", "executed_price": "100", "submitted_at": "1700000000",
            "side": "Buy", "symbol": "AAPL.US", "order_type": "LO", "last_done": "100", "trigger_price": "",
            "msg": "", "tag": "Normal", "time_in_force": "Day", "expire_date": "", "updated_at": "1700000001",
            "trigger_at": "0", "trailing_amount": "", "trailing_percent": "", "limit_offset": "",
            "trigger_status": "NOT_USED", "currency": "USD", "outside_rth": "RTH_ONLY", "remark": "",
            "limit_depth_level": 0, "monitor_price": "", "trigger_count": 0}

def execs(page):
    base = (page - 1) * 3
    return [{"order_id": "1", "trade_id": f"T{base+k}", "symbol": "AAPL.US", "trade_done_at": "1700000000",
             "quantity": "1", "price": "100", "side": "Buy"} for k in range(3)]

CASHFLOW = {"list": [
    {"transaction_flow_name": "BuyContract-Stocks", "direction": 1, "business_type": 2, "balance": "-248.60", "currency": "USD", "business_time": "1621507957", "symbol": "AAPL.US", "description": "AAPL"},
    {"transaction_flow_name": "Dividend", "direction": 2, "business_type": 1, "balance": "12.00", "currency": "USD", "business_time": "1621507958", "symbol": "", "description": "div"}]}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        try:
            return self._get()
        except Exception:
            import traceback; traceback.print_exc(file=sys.stdout); sys.stdout.flush()
            raise
    def _get(self):
        print("HDRS", dict(self.headers), flush=True) if DEBUG else None
        u = urlparse(self.path)
        q = parse_qs(u.query)
        LOG.append(("GET", u.path, u.query))
        p = u.path
        if p == "/v1/asset/account": return self._send(200, env(ACCOUNT))
        if p == "/v1/asset/stock": return self._send(200, env(STOCK))
        if p == "/v1/asset/fund": return self._send(200, env(FUND))
        if p == "/v1/asset/cashflow": return self._send(200, env(CASHFLOW))
        if p == "/v1/trade/order/history":
            return self._send(200, env({"has_more": True, "orders": [order(1), order(2, "CanceledStatus"), order(3, "ExpiredStatus"), order(4, "PartialWithdrawal")]}))
        if p == "/v1/trade/order/today":
            return self._send(200, env({"orders": [order(5, "PartialFilledStatus")]}))
        if p == "/v1/trade/execution/history":
            page = int(q.get("page", ["1"])[0])
            return self._send(200, env({"has_more": page < 3, "trades": execs(page)}))
        if p == "/v1/trade/execution/today":
            return self._send(200, env({"trades": execs(1)}))
        return self._send(404, {"code": 404, "message": "mock: not found " + p})
    def _deny(self):
        u = urlparse(self.path)
        LOG.append((self.command, u.path, u.query))
        return self._send(403, {"code": 403, "message": "mock: mutating call denied"})
    do_POST = do_PUT = do_DELETE = _deny

def start(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":  # run as a separate process: the SDK holds the GIL during calls
    import time

    port = int(sys.argv[1])
    logf = sys.argv[2]
    start(port)
    while True:
        time.sleep(0.2)
        tmp = logf + ".tmp"
        with open(tmp, "w") as fh:  # atomic replace: readers never see a half-written file
            json.dump(LOG, fh)
        os.replace(tmp, logf)
