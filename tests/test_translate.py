"""Translations may change words, never facts."""

import json
from pathlib import Path

import pytest

from cheez.editorial import translate
from cheez.models import Editorial

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "fixtures" / "demo"


@pytest.fixture()
def edition(tmp_path):
    for p in DEMO.glob("editorial*.json"):
        (tmp_path / p.name).write_text(p.read_text())
    return tmp_path, Editorial.model_validate_json((DEMO / "editorial.json").read_text())


def test_demo_translations_are_complete_and_valid(edition):
    d, ed = edition
    tr, warnings = translate.load(d, ed, ["en", "zh-Hant", "zh-Hans"])
    assert warnings == []
    assert tr["zh-Hant"][ed.headline].startswith("示範") and tr["zh-Hans"][ed.headline].startswith("示范")


def _tamper(d: Path, fn):
    p = d / "editorial.zh-Hant.json"
    data = json.loads(p.read_text())
    fn(data)
    p.write_text(json.dumps(data, ensure_ascii=False))


@pytest.mark.parametrize("change", [
    lambda t: t["ideas"][0]["entry"].__setitem__("low", 120.0),          # a level
    lambda t: t["ideas"][0].__setitem__("symbol", "NVDA"),               # a ticker
    lambda t: t["ideas"][0].__setitem__("action", "consider_adding"),     # an action
    lambda t: t["developments"].pop(),                                   # structure
    lambda t: t["ideas"][1].__setitem__("thesis", "這檔股票保證上漲。"),     # certainty language
])
def test_a_translation_that_changes_facts_is_dropped(edition, change):
    d, ed = edition
    _tamper(d, change)
    tr, warnings = translate.load(d, ed, ["en", "zh-Hant", "zh-Hans"])
    assert "zh-Hant" not in tr and "zh-Hans" in tr
    assert any("zh-Hant" in w for w in warnings)


def test_negated_certainty_is_the_disclaimer_and_allowed():
    assert translate._certainty("這是重新評估的點，而不是保證的出場價。") is None
    assert translate._certainty("這是保證的報酬") == "保證"


def test_missing_translation_falls_back_with_a_warning(edition):
    d, ed = edition
    (d / "editorial.zh-Hans.json").unlink()
    tr, warnings = translate.load(d, ed, ["en", "zh-Hant", "zh-Hans"])
    assert set(tr) == {"zh-Hant"} and any("zh-Hans" in w for w in warnings)
