"""One-time read-only authorisation: exchange a Longbridge Agent Auth Code for
an OAuth token, and refuse it unless the granted scopes are read-only.

Why this exists: Longbridge's consent page ticks every scope by default,
including trading, and the official CLI stores its token encrypted to the
machine it ran on, so it cannot be moved to the cloud environment. This command
performs the same documented exchange the CLI and the official MCP server use
(``POST /oauth2/token`` with ``grant_type=authorization_code``), checks the
``scope`` field Longbridge returns, and only then writes the token file.

Run it on your own computer. It never prints the token to the terminal; it
writes it to a file readable only by you, which you then paste into the cloud
environment's settings.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests

OAUTH_TOKEN_URL = "https://openapi.longbridge.com/oauth2/token"
REDIRECT_URI = "https://open.longbridge.com/connect/done"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SCOPE_IDS = {"4": "watchlist", "6": "account.read", "10": "trade.read", "11": "trade.write"}
REFUSE = {"trade.write", "watchlist"}


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        i = B58.find(ch)
        if i < 0:
            raise ValueError("not base58")
        n = n * 58 + i
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw


def unpack_agent_code(code: str) -> Optional[tuple[str, str]]:
    """Layout before base58: [0x01][client_id_len][client_id][authorization code]."""
    raw = code.strip().strip("\"'`")
    try:
        b = b58decode(raw)
    except ValueError:
        return None
    if len(b) < 2 or b[0] != 0x01:
        return None
    n = b[1]
    if len(b) < 2 + n:
        return None
    try:
        client_id = b[2:2 + n].decode()
        auth_code = b[2 + n:].decode()
    except UnicodeDecodeError:
        return None
    return (client_id, auth_code) if client_id and auth_code else None


def legacy_candidates(code: str) -> list[tuple[str, str]]:
    """Older codes: base64(JWT) whose payload carries client_id."""
    out = []
    raw = code.strip().strip("\"'`")
    for cand in {raw, _b64url_to_std(raw)}:
        if not cand:
            continue
        try:
            jwt = base64.b64decode(cand + "=" * (-len(cand) % 4)).decode()
            payload = jwt.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if claims.get("client_id"):
                out.append((claims["client_id"], cand))
        except Exception:
            continue
    return out


def _b64url_to_std(s: str) -> str:
    try:
        return base64.b64encode(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))).decode()
    except Exception:
        return ""


def scopes_of(resp: dict) -> Optional[set[str]]:
    sc = resp.get("scope")
    if sc is None:
        return None
    items = sc.replace(",", " ").split() if isinstance(sc, str) else [str(x) for x in sc]
    return {SCOPE_IDS.get(i, i) for i in items}


def exchange(code: str, session: Optional[requests.Session] = None) -> dict:
    s = session or requests.Session()
    attempts = []
    packed = unpack_agent_code(code)
    if packed:
        attempts.append(packed)
    attempts += legacy_candidates(code)
    if not attempts:
        raise SystemExit("That does not look like a Longbridge Agent Auth Code.")
    last = None
    for client_id, auth_code in attempts:
        region = "us" if auth_code.startswith("us_") else "ap"
        r = s.post(OAUTH_TOKEN_URL, timeout=20, headers={"x-dc-region": region},
                   data={"grant_type": "authorization_code", "code": auth_code,
                         "redirect_uri": REDIRECT_URI, "client_id": client_id})
        if r.ok:
            body = r.json()
            body["client_id"] = client_id
            return body
        last = f"HTTP {r.status_code}"
    raise SystemExit(f"Longbridge rejected the code ({last}). Codes are single-use and expire after a few minutes.")


def build_token_file(resp: dict, now: Optional[int] = None) -> dict:
    now = now or int(time.time())
    scopes = scopes_of(resp)
    if scopes is None:
        raise SystemExit("Longbridge did not report which scopes were granted, so Cheez cannot confirm the token is "
                         "read-only. Nothing was saved. Remove this authorisation in the Longbridge app's security "
                         "settings.")
    bad = scopes & REFUSE
    if bad:
        raise SystemExit("REFUSED: this authorisation includes " + ", ".join(sorted(bad)) + ", which can change your "
                         "account. Nothing was saved. In the Longbridge app, remove the authorisation (security "
                         "settings), then generate a new code with every permission unticked except account "
                         "(and optionally trade lookup).")
    if "account.read" not in scopes:
        raise SystemExit("The authorisation lacks account.read, so Cheez could not read holdings. Nothing was saved.")
    if not resp.get("access_token") or not resp.get("refresh_token"):
        raise SystemExit("The response did not include both an access and a refresh token. Nothing was saved.")
    return {
        "client_id": resp["client_id"],
        "access_token": resp["access_token"],
        "refresh_token": resp["refresh_token"],
        "expires_at": now + int(resp.get("expires_in") or 3600),
        "scope": " ".join(sorted(scopes)),
    }


def main(out: Optional[Path] = None) -> int:
    out = out or Path.home() / ".cheez" / "longbridge-token.json"
    print("Paste the Agent Auth Code from https://open.longbridge.com/connect (input is hidden).")
    print("Before generating it, untick everything except account access (and optionally trade/order lookup).")
    code = getpass.getpass("Agent Auth Code: ")
    tok = build_token_file(exchange(code))
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(out), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # also when the file already existed with wider permissions
    with os.fdopen(fd, "w") as fh:
        json.dump(tok, fh, separators=(",", ":"))
    print(f"Read-only scopes confirmed: {tok['scope']}.")
    print(f"Token saved to {out} (only you can read it). It expires {time.strftime('%d %b %Y', time.gmtime(tok['expires_at']))}"
          " unless refreshed.")
    print("Next: copy that file's single line into the cloud environment variable CHEEZ_LONGBRIDGE_OAUTH "
          "(see docs/SETUP.md). Do not paste it into a chat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
