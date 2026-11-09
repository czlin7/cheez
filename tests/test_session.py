from datetime import date, datetime, timezone

from cheez import session as sess
from cheez.render.site import next_expected_edition

UTC = timezone.utc


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def test_election_day_2026_is_a_trading_day():
    ctx = sess.us_session_context(at("2026-11-03T12:41:00"))
    assert ctx.is_trading_day and ctx.phase == "pre_open"
    assert ctx.open_utc == at("2026-11-03T14:30:00")


def test_thanksgiving_closed_with_name_and_next_session():
    ctx = sess.us_session_context(at("2026-11-26T12:41:00"))
    assert not ctx.is_trading_day and ctx.phase == "closed_day"
    assert ctx.holiday_name and "Thanksgiving" in ctx.holiday_name
    assert ctx.next_session == date(2026, 11, 27)


def test_black_friday_early_close_noted_in_both_timezones():
    ctx = sess.us_session_context(at("2026-11-27T12:41:00"))
    assert ctx.early_close
    assert ctx.close_utc == at("2026-11-27T18:00:00")
    assert any("13:00 New York" in n and "18:00 London" in n for n in ctx.notes)


def test_dst_mismatch_week_is_flagged():
    # US clocks change 2027-03-14, UK on 2027-03-28: the open is 13:30 London in between.
    ctx = sess.us_session_context(at("2027-03-16T11:41:00"))
    assert ctx.open_utc == at("2027-03-16T13:30:00")
    assert any("13:30 London" in n for n in ctx.notes)
    normal = sess.us_session_context(at("2027-04-06T11:41:00"))
    assert not any("out of step" in n for n in normal.notes)


def test_scheduled_start_maps_to_new_york_time_across_dst():
    # 07:41 New York is 12:41 UTC in winter and 11:41 UTC in summer; the cron uses CRON_TZ so both hold.
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    assert datetime(2026, 11, 3, 7, 41, tzinfo=ny).astimezone(UTC).hour == 12
    assert datetime(2027, 6, 1, 7, 41, tzinfo=ny).astimezone(UTC).hour == 11


def test_us_equity_session_labels():
    assert sess.us_equity_session_label(at("2026-11-03T12:30:00")) == "pre_market"
    assert sess.us_equity_session_label(at("2026-11-03T15:00:00")) == "regular_live"
    assert sess.us_equity_session_label(at("2026-11-03T22:00:00")) == "post_market"
    assert sess.us_equity_session_label(at("2026-11-04T03:00:00")) == "overnight"


def test_next_expected_edition_skips_weekends_and_holidays():
    # Wednesday 25 Nov -> next session is Friday 27 Nov (Thanksgiving closed).
    nxt = next_expected_edition(date(2026, 11, 25))
    assert nxt.date() == date(2026, 11, 27)
    # Friday -> Monday
    assert next_expected_edition(date(2026, 11, 6)).date() == date(2026, 11, 9)


def test_latest_completed_session_before_open_is_previous_day():
    assert sess.latest_completed_session(at("2026-11-03T12:00:00")) == date(2026, 11, 2)
    assert sess.latest_completed_session(at("2026-11-03T21:30:00")) == date(2026, 11, 3)


def test_index_label_close_when_exchange_closed():
    # Tokyo was closed on 3 Nov 2026 (Culture Day): a 2 Nov print is that day's close.
    label = sess.exchange_session_label(at("2026-11-02T06:45:00"), "XTKS", at("2026-11-03T12:41:00"))
    assert label == "regular_close"
    assert not sess.is_session(date(2026, 11, 3), "XTKS")


def test_seven_am_london_run_is_for_that_days_session():
    # 06:20 London on Tue 3 Nov is 01:20 New York: the edition is for the session opening 14:30 London.
    ctx = sess.us_session_context(at("2026-11-03T06:20:00"), "Europe/London")
    assert ctx.is_trading_day and ctx.phase == "pre_open" and ctx.edition_date == date(2026, 11, 3)


def test_asian_morning_run_targets_the_coming_us_session():
    # 07:00 Taipei on Monday 9 Nov is Sunday evening in New York.
    ctx = sess.us_session_context(at("2026-11-08T23:00:00"), "Asia/Taipei")
    assert ctx.is_trading_day and ctx.edition_date == date(2026, 11, 9) and ctx.phase == "pre_open"
    # 07:00 Taipei on Tuesday is Monday after the close in New York: still Tuesday's session.
    ctx = sess.us_session_context(at("2026-11-09T23:00:00"), "Asia/Taipei")
    assert ctx.edition_date == date(2026, 11, 10) and ctx.phase == "pre_open"
    # 07:00 Taipei on Thanksgiving (Wednesday evening in New York): no US session that day.
    ctx = sess.us_session_context(at("2026-11-25T23:00:00"), "Asia/Taipei")
    assert not ctx.is_trading_day and ctx.edition_date == date(2026, 11, 26)


def test_evening_run_after_the_close_stays_on_the_same_day():
    ctx = sess.us_session_context(at("2026-11-03T22:00:00"), "Europe/London")
    assert ctx.edition_date == date(2026, 11, 3) and ctx.phase == "post_close"
