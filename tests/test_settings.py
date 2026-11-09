"""User settings: defaults, layering and the schedule they produce."""

from datetime import date, time

import pytest

from cheez import settings


def test_defaults_deliver_at_seven_london_with_a_cron_that_starts_earlier():
    s = settings.load(env={})
    assert s.schedule.deliver_at == "07:00" and s.schedule.timezone == "Europe/London"
    assert s.schedule.cron() == "CRON_TZ=Europe/London 20 6 * * 1-5"
    assert s.report.convert_to == ""  # currency annotation is off by default
    assert s.report.languages == ["en", "zh-Hant", "zh-Hans"]
    assert not s.email.enabled


def test_start_time_avoids_the_busy_minutes():
    s = settings.Schedule(deliver_at="08:00", lead_minutes=30)
    assert s.start_time() == time(7, 27)


def test_toml_then_env_overrides(tmp_path):
    cfg = tmp_path / "cheez.toml"
    cfg.write_text('[schedule]\ndeliver_at = "06:30"\ntimezone = "Asia/Taipei"\n[report]\nconvert_to = "twd"\n')
    s = settings.load(env={"CHEEZ_CONFIG": str(cfg), "CHEEZ_LANGUAGE": "zh-Hant", "CHEEZ_EMAIL_TO": "a@x.test, b@x.test"})
    assert s.schedule.timezone == "Asia/Taipei" and s.schedule.city == "Taipei"
    assert s.report.convert_to == "TWD" and s.report.default_language == "zh-Hant"
    assert s.email.to == ["a@x.test", "b@x.test"] and s.email.enabled
    assert s.schedule.deliver_utc(date(2026, 11, 3)).hour == 22  # 06:30 Taipei is 22:30 UTC the day before


def test_inline_toml_from_environment():
    s = settings.load(env={"CHEEZ_CONFIG": "/nonexistent", "CHEEZ_CONFIG_TOML": '[email]\nenabled = true\nto = ["me@x.test"]\n'})
    assert s.email.enabled and s.email.to == ["me@x.test"]


@pytest.mark.parametrize("bad", ['[report]\nconvert_to = "XYZ"', '[schedule]\ntimezone = "Mars/Base"',
                                 '[schedule]\ndeliver_at = "25:00"', '[report]\ndefault_language = "fr"'])
def test_invalid_settings_are_refused(bad):
    with pytest.raises(Exception):
        settings.load(env={"CHEEZ_CONFIG": "/nonexistent", "CHEEZ_CONFIG_TOML": bad})


def test_english_is_always_written():
    s = settings.load(env={"CHEEZ_CONFIG": "/nonexistent", "CHEEZ_LANGUAGES": "zh-Hant"})
    assert s.report.languages == ["en", "zh-Hant"]


def test_schedule_prompt_names_the_artifact_and_email_step():
    from cheez.schedule import describe, prompt

    s = settings.load(env={"CHEEZ_CONFIG": "/nonexistent", "CHEEZ_ARTIFACT_URL": "https://claude.ai/code/artifact/x",
                           "CHEEZ_EMAIL_TO": "me@x.test"})
    p = prompt(s, "claude")
    assert "https://claude.ai/code/artifact/x" in p and "cheez email --send" in p
    assert "artifact" not in prompt(s, "codex").lower().replace("no claude artifact", "")
    assert "CRON_TZ=Europe/London 20 6 * * 1-5" in describe(s)
