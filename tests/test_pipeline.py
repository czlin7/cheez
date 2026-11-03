"""End-to-end pipeline on synthetic data: duplicate runs, revisions, interrupted
runs, closed markets, failure handling and state carried inside the page."""

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
NOW = datetime(2026, 11, 3, 12, 45, tzinfo=UTC)  # 07:45 New York


def _write_editorial(res, eid="2026-11-03-us"):
    d = json.loads((ROOT / "fixtures/demo/editorial.json").read_text())
    d["edition_id"] = eid
    Path(res.editorial_path).write_text(json.dumps(d))


def test_full_run_then_duplicate_is_skipped(cheez_home, offline_pipeline):
    from cheez import pipeline

    res = pipeline.prepare(NOW, trigger="scheduled")
    assert res.outcome == "ready" and res.edition_id == "2026-11-03-us"
    brief = Path(res.brief_path).read_text()
    assert "cost" not in brief.lower().split("## portfolio")[1].split("##")[0].replace("no cost basis", "")
    _write_editorial(res)
    out = pipeline.render(res.edition_id, now=NOW + timedelta(minutes=30))
    assert out["run_status"] in ("succeeded", "partial")
    again = pipeline.prepare(NOW + timedelta(hours=1), trigger="scheduled")
    assert again.outcome == "duplicate"
    from cheez.state import Store

    st = Store(cheez_home).load()
    assert len(st.editions) == 1
    assert [r.status for r in st.runs][-1] == "skipped_duplicate"


def test_forced_rerun_is_a_numbered_revision_not_a_new_edition(cheez_home, offline_pipeline):
    from cheez import pipeline
    from cheez.state import Store

    res = pipeline.prepare(NOW)
    _write_editorial(res)
    pipeline.render(res.edition_id, now=NOW + timedelta(minutes=30))
    res2 = pipeline.prepare(NOW + timedelta(hours=2), force=True)
    assert res2.outcome == "ready"
    pack = pipeline.load_pack(res2.edition_id)
    assert pack.revision == 2
    _write_editorial(res2)
    pipeline.render(res2.edition_id, now=NOW + timedelta(hours=2, minutes=20))
    st = Store(cheez_home).load()
    assert len(st.editions) == 1 and len(st.ledger.entries) == 3  # no duplicated ideas either


def test_concurrent_run_is_refused_and_stale_run_is_closed_out(cheez_home, offline_pipeline):
    from cheez import pipeline
    from cheez.state import Store

    pipeline.prepare(NOW)
    busy = pipeline.prepare(NOW + timedelta(minutes=20))
    assert busy.outcome == "in_progress"
    later = pipeline.prepare(NOW + timedelta(hours=5))  # the first run never finished
    assert later.outcome == "ready"
    st = Store(cheez_home).load()
    assert any(r.status == "failed" and "did not finish" in " ".join(r.problems) for r in st.runs)


def test_closed_market_day_publishes_a_note_without_ideas(cheez_home, offline_pipeline):
    from cheez import pipeline

    thanksgiving = datetime(2026, 11, 26, 12, 45, tzinfo=UTC)
    res = pipeline.prepare(thanksgiving)
    assert res.outcome == "closed"
    out = pipeline.render(res.edition_id, closed=True, now=thanksgiving + timedelta(minutes=5))
    html = Path(out["preview_file"]).read_text()
    assert out["status"] == "closed"
    assert "Thanksgiving" in html
    assert 'id="ideas"' not in html


def test_failed_editorial_falls_back_to_labelled_market_only_edition(cheez_home, offline_pipeline):
    from cheez import pipeline

    res = pipeline.prepare(NOW)
    out = pipeline.fail(res.edition_id, "research step exceeded its time budget")
    assert out["status"] == "partial"
    html = Path(out["preview_file"]).read_text()
    assert "Commentary and ideas unavailable" in html and "Partial data" in html


def test_invalid_editorial_blocks_rendering(cheez_home, offline_pipeline):
    from cheez import pipeline

    res = pipeline.prepare(NOW)
    d = json.loads((ROOT / "fixtures/demo/editorial.json").read_text())
    d["edition_id"] = res.edition_id
    d["ideas"][0]["thesis"] = "A guaranteed winner."
    Path(res.editorial_path).write_text(json.dumps(d))
    with pytest.raises(SystemExit):
        pipeline.render(res.edition_id)


def test_state_travels_inside_the_published_page(cheez_home, offline_pipeline, tmp_path, monkeypatch):
    from cheez import pipeline
    from cheez.state import Store

    res = pipeline.prepare(NOW)
    _write_editorial(res)
    out = pipeline.render(res.edition_id, now=NOW + timedelta(minutes=30))
    page = Path(out["publish_file"]).read_text()
    assert "<html" not in page.lower()[:200] and "<title>Cheez Daily</title>" in page[:8192]
    # A fresh container: nothing local, only the page that was published.
    fresh = tmp_path / "fresh"
    monkeypatch.setenv("CHEEZ_HOME", str(fresh))
    saved = tmp_path / "published.html"
    saved.write_text(page)
    nxt = NOW + timedelta(days=1)
    res2 = pipeline.prepare(nxt, state_from=saved)
    assert res2.edition_id == "2026-11-04-us"
    st = Store(fresh).load()
    assert len(st.ledger.entries) == 3 and st.editions[0].id == "2026-11-03-us"
    assert (fresh / "state" / "archive" / "2026-11-03-us.html").exists()
    brief = Path(res2.brief_path).read_text()
    assert "Previous edition (2026-11-03-us)" in brief
    d = json.loads((ROOT / "fixtures/demo/editorial.json").read_text())
    d["edition_id"] = res2.edition_id
    for i in d["ideas"]:
        i["idea_id"] = i["idea_id"].replace("2026-11-03", "2026-11-04")
    Path(res2.editorial_path).write_text(json.dumps(d))
    out2 = pipeline.render(res2.edition_id, now=nxt + timedelta(minutes=30))
    page2 = Path(out2["publish_file"]).read_text()
    assert 'id="tpl-2026-11-03-us"' in page2 and 'href="#ed-2026-11-03-us"' in page2


def test_page_contains_no_account_identifiers_or_secrets(cheez_home, offline_pipeline, monkeypatch):
    from cheez import pipeline

    monkeypatch.setenv("CHEEZ_LONGBRIDGE_OAUTH", json.dumps({"client_id": "cid-123", "access_token": "SECRET-ACCESS",
                                                             "refresh_token": "SECRET-REFRESH"}))
    res = pipeline.prepare(NOW)
    _write_editorial(res)
    out = pipeline.render(res.edition_id, now=NOW + timedelta(minutes=30))
    page = Path(out["publish_file"]).read_text()
    for needle in ("SECRET-ACCESS", "SECRET-REFRESH", "cid-123", "member_id"):
        assert needle not in page
    assert out["bytes"] < 16 * 1024 * 1024


def test_stale_and_missing_instruments_mark_the_edition_partial(cheez_home, offline_pipeline, monkeypatch):
    from cheez import pipeline

    real = pipeline.build_snapshot

    def stale_snapshot(f, now, specs=None):
        m = real(f, now)
        m.instruments[0].stale = True
        m.instruments[0].stale_reason = "Latest value is from Thu 29 Oct."
        m.instruments[1].last = None
        return m

    monkeypatch.setattr(pipeline, "build_snapshot", stale_snapshot)
    res = pipeline.prepare(NOW)
    _write_editorial(res)
    out = pipeline.render(res.edition_id, now=NOW + timedelta(minutes=30))
    assert out["status"] == "partial"
    html = Path(out["preview_file"]).read_text()
    assert "Stale: Latest value is from Thu 29 Oct." in html and "Partial data" in html


def test_demo_is_separate_and_labelled(cheez_home):
    from cheez.demo import build_demo

    out = build_demo()
    assert "/demo/" in out["publish_file"]
    html = Path(out["preview_file"]).read_text()
    assert "Demonstration edition." in html
    assert re.search(r"fictional", html)
    assert not (cheez_home / "site" / "index.html").exists()  # live site untouched
