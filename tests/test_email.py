"""The emailed digest and its delivery."""

import pytest


@pytest.fixture()
def demo_edition(cheez_home, monkeypatch):
    from cheez.demo import build_demo

    build_demo()
    monkeypatch.setenv("CHEEZ_HOME", str(cheez_home / "demo"))
    return "2026-11-03-us"


def _cfg(env):
    from cheez import settings

    return settings.load(env={"CHEEZ_CONFIG": "/nonexistent", **env})


def test_digest_is_built_in_the_configured_language(demo_edition, monkeypatch):
    from cheez import settings
    from cheez.delivery import email

    monkeypatch.setenv("CHEEZ_LANGUAGE", "zh-Hant")
    monkeypatch.setenv("CHEEZ_CONVERT_TO", "HKD")
    settings.reset()
    try:
        b = email.build(demo_edition)
    finally:
        settings.reset()
    assert "示範" in b.subject and "今日交易清單" in b.html
    assert "≈HK$" in b.html and "<ruby" not in b.html and "data-zh" not in b.html
    assert "<script" not in b.html and "<svg" not in b.html
    assert "Harbourline is now" not in b.text  # translated plain-text part too


def test_portfolio_is_left_out_unless_asked(demo_edition):
    from cheez.delivery import email

    b = email.build(demo_edition)
    assert "The demo account is concentrated" not in b.html


def test_send_refuses_when_not_enabled(demo_edition):
    from cheez.delivery import email

    b = email.build(demo_edition)
    with pytest.raises(SystemExit):
        email.send(b, _cfg({}), env={})


def test_smtp_delivery(demo_edition, monkeypatch):
    from cheez.delivery import email

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["host"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, pw):
            sent["login"] = (user, pw)

        def send_message(self, msg):
            sent["to"] = msg["To"]

    monkeypatch.setattr(email.smtplib, "SMTP", FakeSMTP)
    cfg = _cfg({"CHEEZ_EMAIL_TO": "me@x.test", "CHEEZ_SMTP_HOST": "smtp.x.test", "CHEEZ_SMTP_USER": "me"})
    detail = email.send(email.build(demo_edition), cfg, env={"CHEEZ_SMTP_PASSWORD": "pw"})
    assert "SMTP" in detail and sent == {"host": ("smtp.x.test", 587), "tls": True, "login": ("me", "pw"), "to": "me@x.test"}


def test_resend_delivery(demo_edition, monkeypatch):
    import requests

    from cheez.delivery import email

    calls = {}

    class R:
        status_code = 200
        text = "{}"

    def post(url, timeout, headers, json):
        calls.update(url=url, auth=headers["Authorization"], to=json["to"])
        return R()

    monkeypatch.setattr(requests, "post", post)
    cfg = _cfg({"CHEEZ_EMAIL_TO": "me@x.test", "CHEEZ_EMAIL_PROVIDER": "resend"})
    email.send(email.build(demo_edition), cfg, env={"CHEEZ_RESEND_API_KEY": "re_123"})
    assert calls == {"url": email.RESEND_URL, "auth": "Bearer re_123", "to": ["me@x.test"]}
