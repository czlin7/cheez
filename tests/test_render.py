"""The page: playbook, language switch, convertible prices, settings."""

import re
from pathlib import Path

from markupsafe import Markup

from cheez.render import format as fmt


def test_demo_page_has_playbook_languages_and_convertible_prices(cheez_home):
    from cheez.demo import build_demo

    out = build_demo()
    html = Path(out["preview_file"]).read_text()
    assert 'id="playbook"' in html and "Today&#39;s playbook" in html or "Today's playbook" in html
    assert 'data-zh-hant="今日交易清單"' in html and 'data-zh-hans="今日交易清单"' in html
    assert 'class="m" data-v="' in html  # prices carry their value for conversion
    assert 'id="settings"' in html and 'class="cheez-fx"' in html
    assert "<rt>" not in html  # conversion is off by default
    assert Path(out["email_preview"]).exists()


def test_server_side_conversion_when_configured(cheez_home, monkeypatch):
    from cheez import settings
    from cheez.demo import build_demo

    monkeypatch.setenv("CHEEZ_CONVERT_TO", "GBP")
    settings.reset()
    try:
        html = Path(build_demo()["preview_file"]).read_text()
    finally:
        settings.reset()
    assert re.search(r"<rt>≈£[\d,]+\.\d\d</rt>", html)


def test_prose_dollar_amounts_become_convertible():
    with fmt.rendering(fmt.RenderOptions(convert_to="GBP", per_usd={"USD": 1.0, "GBP": 0.8})):
        out = str(fmt.tx("Revenue of $1.9bn and a target near $188."))
    assert 'data-v="1900000000" data-c="USD" data-s="bn"' in out and "≈£1.5bn" in out
    assert "≈£150.40" in out


def test_text_is_escaped_before_prices_are_marked_up():
    with fmt.rendering(fmt.RenderOptions()):
        out = fmt.tx('<script>alert("x")</script> costs $5')
    assert isinstance(out, Markup) and "<script>" not in out and "&lt;script&gt;" in out


def test_conversion_rules():
    rates = {"USD": 1.0, "JPY": 150.0, "HKD": 7.8}
    assert fmt.converted(100, "USD", "JPY", rates) == "≈¥15,000"
    assert fmt.converted(78, "HKD", "USD", rates) == "≈$10.00"
    assert fmt.converted(100, "USD", "USD", rates) is None
    assert fmt.converted(100, "USD", "CHF", rates) is None  # no rate, no guess
