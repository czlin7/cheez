"""Durable private state.

Cheez keeps its memory (idea ledger, run log, edition index, recent archive)
in two places:

* ``var/state/`` locally (gitignored), for development and manual runs;
* inside the published private page itself, as a JSON block plus one
  ``<template>`` per archived edition. A scheduled run reads the current page,
  imports that state, and republishes the page with the new edition added. The
  page is therefore its own durable store and every publish is a version.

Nothing here is ever written to the public repository.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .models import Ledger, RunRecord

STATE_VERSION = 1
MAX_ARCHIVE_EDITIONS = 90  # recent editions kept inside the page (~4 months of weekdays)


class EditionEntry(BaseModel):
    id: str
    date: date
    headline: str
    status: str  # complete | partial | closed | failed | demo
    published_at: datetime


class State(BaseModel):
    version: int = STATE_VERSION
    ledger: Ledger = Field(default_factory=Ledger)
    runs: list[RunRecord] = Field(default_factory=list)
    editions: list[EditionEntry] = Field(default_factory=list)
    last_editorial: Optional[dict] = None  # previous edition's editorial, for "since last edition"
    last_market: Optional[dict] = None  # previous edition's key levels
    demo: bool = False


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.state_dir = root / "state"
        self.archive_dir = self.state_dir / "archive"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    def load(self) -> State:
        if self.state_file.exists():
            return State.model_validate_json(self.state_file.read_text())
        return State()

    def save(self, st: State) -> None:
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(st.model_dump_json(indent=1))
        tmp.replace(self.state_file)

    def archive_put(self, edition_id: str, main_html: str) -> None:
        (self.archive_dir / f"{edition_id}.html").write_text(main_html)

    def archive_get(self, edition_id: str) -> Optional[str]:
        p = self.archive_dir / f"{edition_id}.html"
        return p.read_text() if p.exists() else None

    def archive_ids(self) -> list[str]:
        return sorted((p.stem for p in self.archive_dir.glob("*.html")), reverse=True)

    def edition_dir(self, edition_id: str) -> Path:
        d = self.root / "editions" / edition_id
        d.mkdir(parents=True, exist_ok=True)
        return d


# ---------------------------------------------------------------------------
# Embedding state in the published page, and reading it back
# ---------------------------------------------------------------------------

STATE_SCRIPT_ID = "cheez-state"
_TPL_RE = re.compile(r'<template id="tpl-([0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z-]+)">(.*?)</template>', re.S)
_MAIN_RE = re.compile(r'<main id="edition"[^>]*data-edition="([0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z-]+)"[^>]*>(.*?)</main>', re.S)
_STATE_RE = re.compile(r'<script type="application/json" id="cheez-state">(.*?)</script>', re.S)


def state_script(st: State) -> str:
    raw = st.model_dump_json()
    # Make the JSON safe inside <script>: no "</" sequences, no HTML comments.
    raw = raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'<script type="application/json" id="{STATE_SCRIPT_ID}">{raw}</script>'


def archive_templates(items: list[tuple[str, str]]) -> str:
    return "\n".join(f'<template id="tpl-{eid}">{body}</template>' for eid, body in items)


def import_page(page_html: str, store: Store) -> State:
    """Restore state and archive from a previously published page."""
    m = _STATE_RE.search(page_html)
    if not m:
        raise ValueError("The page does not contain Cheez state; is this the right artifact?")
    raw = m.group(1)
    st = State.model_validate(json.loads(raw))
    for eid, body in _TPL_RE.findall(page_html):
        store.archive_put(eid, body)
    m = _MAIN_RE.search(page_html)  # the latest edition is the page body itself, not a template
    if m:
        store.archive_put(m.group(1), m.group(2).strip())
    store.save(st)
    return st


def unescape_attr(s: str) -> str:
    return html.unescape(s)
