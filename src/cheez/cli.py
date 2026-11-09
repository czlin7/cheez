"""Command line for Cheez. Every command is safe to re-run.

  cheez prepare [--trigger scheduled|manual] [--force] [--state-from PAGE.html]
  cheez add-stocks SYMBOL [SYMBOL ...]
  cheez refresh
  cheez check
  cheez render [--closed | --market-only REASON]
  cheez fail REASON
  cheez email [--send] [--force]
  cheez config [show|init|path]
  cheez schedule [--agent claude|codex]
  cheez status
  cheez demo
  cheez brokerage-check
  cheez brokerage-authorize
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _eid(args) -> str:
    from .pipeline import latest_edition_id

    eid = getattr(args, "edition", None) or latest_edition_id()
    if not eid:
        sys.exit("No prepared edition found. Run `cheez prepare` first.")
    return eid


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheez", description="Cheez Daily: private, read-only market briefing.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare", help="Fetch facts and write the research brief")
    p.add_argument("--trigger", default="manual", choices=["scheduled", "manual", "test"])
    p.add_argument("--force", action="store_true", help="Publish a revision even if today's edition exists")
    p.add_argument("--state-from", type=Path, help="Published page to restore ledger/archive/run log from")
    p.add_argument("--now", help="ISO timestamp override (testing)")

    p = sub.add_parser("add-stocks", help="Add verified facts for more tickers")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--edition")

    p = sub.add_parser("refresh", help="Re-fetch prices for the edition in progress (before checking)")
    p.add_argument("--edition")

    p = sub.add_parser("check", help="Validate editorial.json against the facts")
    p.add_argument("--edition")

    p = sub.add_parser("render", help="Render the edition and the publishable page")
    p.add_argument("--edition")
    p.add_argument("--closed", action="store_true", help="Market-closed note without commentary")
    p.add_argument("--market-only", metavar="REASON", help="Publish market data without commentary, stating why")

    p = sub.add_parser("fail", help="Record a failed run (publishes market data if available)")
    p.add_argument("reason")
    p.add_argument("--edition")

    p = sub.add_parser("email", help="Build the email digest of the latest edition; --send delivers it")
    p.add_argument("--edition")
    p.add_argument("--send", action="store_true", help="Send to the configured recipients")
    p.add_argument("--force", action="store_true", help="Send again even if this revision was already sent")

    p = sub.add_parser("config", help="Show settings, or write a starter cheez.toml")
    p.add_argument("action", nargs="?", default="show", choices=["show", "init", "path"])

    p = sub.add_parser("schedule", help="Print the cron line and scheduled-task prompt for your delivery time")
    p.add_argument("--agent", default="claude", choices=["claude", "codex"])

    sub.add_parser("status", help="Show recent runs")
    p = sub.add_parser("demo", help="Build the clearly-labelled demonstration edition from fixtures")
    p.add_argument("--live-market", action="store_true", help="Use live market data with the fictional portfolio")
    sub.add_parser("brokerage-check", help="Check the read-only Longbridge configuration (no account data printed)")
    p = sub.add_parser("brokerage-authorize", help="One-time: exchange a Longbridge Agent Auth Code for a read-only token")
    p.add_argument("--out", type=Path, help="Where to write the token file (default ~/.cheez/longbridge-token.json)")

    args = ap.parse_args(argv)

    if args.cmd == "prepare":
        from .pipeline import prepare

        now = datetime.fromisoformat(args.now).astimezone(timezone.utc) if args.now else None
        res = prepare(now, trigger=args.trigger, force=args.force, state_from=args.state_from)
        print(json.dumps(res.model_dump(), indent=1))
        return {"ready": 0, "closed": 0, "duplicate": 3, "in_progress": 4}[res.outcome]

    if args.cmd == "add-stocks":
        from .pipeline import add_stocks

        print(json.dumps(add_stocks(_eid(args), args.symbols), indent=1))
        return 0

    if args.cmd == "refresh":
        from .pipeline import refresh

        print(json.dumps(refresh(_eid(args)), indent=1, default=str))
        return 0

    if args.cmd == "check":
        from .pipeline import check

        _, rep = check(_eid(args))
        print(json.dumps({"ok": rep.ok, "errors": rep.errors, "warnings": rep.warnings}, indent=1))
        return 0 if rep.ok else 1

    if args.cmd == "render":
        from .pipeline import render

        out = render(_eid(args), closed=args.closed, market_only_reason=args.market_only)
        print(json.dumps(out, indent=1, default=str))
        return 0

    if args.cmd == "fail":
        from .pipeline import fail, latest_edition_id

        out = fail(args.edition or latest_edition_id(), args.reason)
        print(json.dumps(out, indent=1, default=str))
        return 0

    if args.cmd == "email":
        from .delivery import email as mail
        from .pipeline import load_pack
        from .state import Store
        from .config import var_dir

        eid = _eid(args)
        built = mail.build(eid)
        out = {"subject": built.subject, "html": str(built.html_path), "eml": str(built.eml_path), "sent": False}
        if args.send:
            d = Store(var_dir()).edition_dir(eid)
            rev = load_pack(eid).revision
            if mail.already_sent(d, rev) and not args.force:
                out["detail"] = "already sent for this revision; use --force to send again"
            else:
                out["detail"] = mail.send(built)
                mail.mark_sent(d, rev, out["detail"])
                out["sent"] = True
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0

    if args.cmd == "config":
        from . import settings

        if args.action == "path":
            print("\n".join(str(p) for p in settings.config_paths()))
            return 0
        if args.action == "init":
            target = settings.config_paths()[0]
            if target.exists():
                sys.exit(f"{target} already exists; edit it instead.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(settings.STARTER)
            print(f"Wrote {target}")
            return 0
        cfg = settings.get()
        data = cfg.model_dump(mode="json", by_alias=True)
        data["email"]["to"] = [f"{len(cfg.email.to)} recipient(s)"] if cfg.email.to else []
        print(json.dumps({"sources": cfg.source, "settings": data}, indent=1, ensure_ascii=False))
        return 0

    if args.cmd == "schedule":
        from .schedule import describe
        from .settings import get

        print(describe(get(), args.agent))
        return 0

    if args.cmd == "status":
        from .config import var_dir
        from .state import Store

        st = Store(var_dir()).load()
        for r in st.runs[-12:]:
            print(f"{r.edition_id}  rev {r.revision}  {r.status:<18} started {r.started_at:%Y-%m-%d %H:%M}Z  "
                  f"{'; '.join(r.problems)[:160]}")
        if not st.runs:
            print("No runs recorded.")
        return 0

    if args.cmd == "demo":
        from .demo import build_demo

        print(json.dumps(build_demo(live_market=args.live_market), indent=1, default=str))
        return 0

    if args.cmd == "brokerage-authorize":
        from .brokerage.authorize import main as authorize

        return authorize(args.out)

    if args.cmd == "brokerage-check":
        from .brokerage.longbridge import check_boundary

        chk = check_boundary()
        print(json.dumps({"ok": chk.ok, "reason": chk.reason, "scopes": sorted(chk.scopes or []),
                          "scope_source": chk.scope_source,
                          "expires_at": chk.expires_at.isoformat() if chk.expires_at else None,
                          "warnings": chk.warnings}, indent=1))
        return 0 if chk.ok else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
