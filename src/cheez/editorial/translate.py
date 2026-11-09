"""Translations of the editorial, written by the model as parallel files.

For each extra language the writer saves ``editorial.<lang>.json``: the same
JSON as ``editorial.json`` with only the prose translated. Code walks the two
documents side by side, so a translation can never change a number, a ticker,
an action, a level or a link; any structural difference drops that language
(with a warning) instead of blocking the edition. The result is a lookup from
each English string to its translation, used by the renderer.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..models import Editorial

# Keys whose string values are identifiers or enumerations, not prose: they must match exactly.
FIXED_KEYS = {
    "edition_id", "idea_id", "symbol", "url", "status", "kind", "relation", "label", "action", "confidence",
    "meaning", "instrument_key", "revision_of", "published_at", "event_date", "when", "basis", "tickers",
}
# Certainty language in Chinese, mirroring the English rules in validate.py.
FORBIDDEN_ZH = re.compile(r"保證|保证|穩賺|稳赚|無風險|无风险|必漲|必涨|一定會漲|一定会涨|底部已現|底部已现")
NEGATION_ZH = re.compile(r"(不|非|沒|没|無|无|未)[^。；，,]{0,8}$")


def is_fixed(key: str, parent: str) -> bool:
    """Identifiers and enums are fixed; a horizon's label ("3–6 months") is prose, a read-through's is not."""
    return key in FIXED_KEYS and not (key == "label" and parent == "horizon")


def _certainty(text: str) -> str | None:
    for m in FORBIDDEN_ZH.finditer(text):
        if not NEGATION_ZH.search(text[max(0, m.start() - 10):m.start()]):  # "不是保證的出場價" is the disclaimer we want
            return m.group(0)
    return None


def _walk(en: Any, tr: Any, path: str, out: dict[str, str], problems: list[str], fixed: bool = False) -> None:
    if isinstance(en, dict):
        if not isinstance(tr, dict) or set(en) != set(tr):
            problems.append(f"{path or 'root'}: fields differ from the English editorial")
            return
        parent = path.rsplit(".", 1)[-1]
        for k in en:
            _walk(en[k], tr[k], f"{path}.{k}" if path else k, out, problems, fixed or is_fixed(k, parent))
    elif isinstance(en, list):
        if not isinstance(tr, list) or len(en) != len(tr):
            problems.append(f"{path}: list length differs from the English editorial")
            return
        for i, (a, b) in enumerate(zip(en, tr)):
            _walk(a, b, f"{path}[{i}]", out, problems, fixed)
    elif isinstance(en, str):
        if not isinstance(tr, str):
            problems.append(f"{path}: expected text")
        elif fixed:
            if en != tr:
                problems.append(f"{path}: {en!r} must not be translated or changed")
        elif tr.strip() and tr != en:
            bad = _certainty(tr)
            if bad:
                problems.append(f"{path}: certainty language is not allowed ({bad})")
            out[en] = tr
    elif en != tr:
        problems.append(f"{path}: value {en!r} must be identical in every language")


def load(edition_dir: Path, editorial: Editorial, languages: list[str]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Return ``{lang: {english: translated}}`` for each valid translation file, and warnings."""
    base = editorial.model_dump(mode="json")
    out: dict[str, dict[str, str]] = {}
    warnings: list[str] = []
    for lang in languages:
        if lang == "en":
            continue
        p = edition_dir / f"editorial.{lang}.json"
        if not p.exists():
            warnings.append(f"No {lang} translation was written; that language falls back to English.")
            continue
        try:
            tr = Editorial.model_validate_json(p.read_text()).model_dump(mode="json")
        except Exception as e:
            warnings.append(f"{lang} translation does not match the schema and was dropped: {str(e)[:300]}")
            continue
        mapping: dict[str, str] = {}
        problems: list[str] = []
        _walk(base, tr, "", mapping, problems)
        if problems:
            warnings.append(f"{lang} translation dropped: " + "; ".join(problems[:5]))
            continue
        out[lang] = mapping
    return out, warnings
