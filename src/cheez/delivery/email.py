"""The emailed edition: a short, scannable digest in the reader's language,
with a link to the full private page.

``build`` renders HTML and plain text from an edition that has already been
rendered. ``send`` delivers it by SMTP or the Resend HTTP API. Holdings are
left out unless ``email.include_portfolio`` is set, because email is stored on
third-party servers. Credentials come only from the environment
(``CHEEZ_SMTP_PASSWORD`` or ``CHEEZ_RESEND_API_KEY``), never from settings
files.
"""

from __future__ import annotations

import json
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Optional

from .. import i18n
from .. import settings as settings_mod
from ..render import charts, site

UTC = timezone.utc
RESEND_URL = "https://api.resend.com/emails"


@dataclass
class Built:
    subject: str
    html: str
    text: str
    html_path: Path
    eml_path: Path


def _text_version(view: dict, page_url: str, lang: str) -> str:
    from markupsafe import Markup

    def plain(x) -> str:
        return Markup(str(x)).striptags()

    ed = view["editorial"]
    out = [plain(site._env().filters["tx"](ed.headline)), ""]
    for t in ed.tldr:
        out.append("- " + plain(site._env().filters["tx"](t)))
    out += ["", i18n.ui_text("Today's playbook", lang).upper()]
    for c in view["playbook"]["cards"]:
        i = c["idea"]
        line = f"{c['rank']}. {i.symbol}: {plain(site._env().filters['action_text'](i.action))}"
        if i.entry:
            line += f" | {i18n.ui_text('Entry zone', lang)} {i.entry.low:,.2f}-{i.entry.high:,.2f}"
        if i.invalidation:
            line += f" | {i18n.ui_text('Invalidation', lang)} {i.invalidation.level:,.2f}"
        out += [line, "   " + plain(site._env().filters["tx"](c["why"]))]
    if not view["playbook"]["cards"]:
        out.append(i18n.ui_text("No trade today", lang))
    if page_url:
        out += ["", page_url]
    out += ["", "Research, not investment advice. Cheez never places orders."]
    return "\n".join(out)


def build(edition_id: str, out_dir: Optional[Path] = None) -> Built:
    from ..config import var_dir
    from ..editorial import translate
    from ..models import RunRecord
    from ..pipeline import check, load_pack
    from ..state import Store

    cfg = settings_mod.get()
    pack = load_pack(edition_id)
    store = Store(var_dir())
    d = store.edition_dir(edition_id)
    editorial, rep = check(edition_id)
    if editorial is None or not rep.ok:
        raise SystemExit("This edition has no publishable editorial; there is nothing to email.")
    lang = cfg.email_language
    translations, _ = translate.load(d, editorial, cfg.report.languages)
    opts = site.render_options(pack.market, translations, lang=lang, convert_to=cfg.email_currency, fx_mode="inline")
    opts.langs = (lang,)  # one language per email; no switching markup
    meta = site.EditionMeta(id=edition_id, date=pack.edition_date, kind_label=pack.kind_label,
                            published_at=datetime.now(tz=UTC), data_cutoff=pack.market.data_cutoff,
                            status="demo" if pack.demo else "complete", demo=pack.demo, revision=pack.revision)
    run = RunRecord(edition_id=edition_id, started_at=pack.prepared_at, status="succeeded")
    with site.rendering(opts):
        view = site.build_view(edition=meta, market=pack.market, stocks=pack.stocks, editorial=editorial, report=rep,
                               portfolio=pack.portfolio if cfg.email.include_portfolio else None,
                               state=store.load(), run=run)
        for c in view["playbook"]["cards"]:
            f = c["facts"]
            c["spark_text"] = charts.text_sparkline([b.c for b in f.history[-63:]]) if f else ""
        for p in view["pulse"]:
            p["spark_text"] = charts.text_sparkline([b.c for b in p["inst"].history[-44:]], width=16)
        env = site._env()
        headline = str(env.filters["tx"](editorial.headline).striptags())
        subject = f"{cfg.email.subject_prefix} · {pack.edition_date:%-d %b}: {headline}"
        html = env.get_template("email.html.j2").render(
            v=view, page_url=cfg.email.page_url, include_portfolio=cfg.email.include_portfolio,
            html_lang=i18n.HTML_LANG.get(lang, "en"), date_label=i18n.long_date(pack.edition_date, lang), subject=subject,
            city=opts.city)
        text = _text_version(view, cfg.email.page_url, lang)
    out_dir = out_dir or (var_dir() / ("site-demo" if pack.demo else "site"))
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path, eml_path = out_dir / "email.html", out_dir / "email.eml"
    html_path.write_text(html)
    eml_path.write_bytes(bytes(_message(subject, html, text, cfg)))
    return Built(subject=subject, html=html, text=text, html_path=html_path, eml_path=eml_path)


def _message(subject: str, html: str, text: str, cfg: settings_mod.Settings) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.email.from_
    msg["To"] = ", ".join(cfg.email.to) or "undisclosed-recipients:;"
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain="cheez.local")
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send(built: Built, cfg: Optional[settings_mod.Settings] = None, env: Optional[dict] = None) -> str:
    cfg = cfg or settings_mod.get()
    env = dict(os.environ if env is None else env)
    e = cfg.email
    if not e.enabled or not e.to:
        raise SystemExit("Email is not enabled: set [email] enabled = true and to = [...] (or CHEEZ_EMAIL_TO).")
    if e.provider == "resend":
        import requests

        # The key may be injected by the cloud environment's network proxy instead of the environment.
        key = env.get("CHEEZ_RESEND_API_KEY") or "proxy-injected"
        r = requests.post(RESEND_URL, timeout=30, headers={"Authorization": f"Bearer {key}"},
                          json={"from": e.from_, "to": e.to, "subject": built.subject, "html": built.html,
                                "text": built.text})
        if r.status_code >= 300:
            raise SystemExit(f"Resend refused the email: HTTP {r.status_code} {r.text[:200]}")
        return f"sent via Resend to {len(e.to)} recipient(s)"
    if not e.smtp_host:
        raise SystemExit("Set [email] smtp_host (and smtp_user; the password goes in CHEEZ_SMTP_PASSWORD).")
    msg = _message(built.subject, built.html, built.text, cfg)
    with smtplib.SMTP(e.smtp_host, e.smtp_port, timeout=30) as s:
        if e.smtp_starttls:
            s.starttls()
        if e.smtp_user:
            s.login(e.smtp_user, env.get("CHEEZ_SMTP_PASSWORD", ""))
        s.send_message(msg)
    return f"sent via SMTP ({e.smtp_host}) to {len(e.to)} recipient(s)"


def mark_sent(edition_dir: Path, revision: int, detail: str) -> None:
    (edition_dir / "email.sent.json").write_text(json.dumps({"revision": revision, "detail": detail,
                                                             "at": datetime.now(tz=UTC).isoformat()}))


def already_sent(edition_dir: Path, revision: int) -> bool:
    p = edition_dir / "email.sent.json"
    try:
        return p.exists() and json.loads(p.read_text()).get("revision") == revision
    except Exception:
        return False
