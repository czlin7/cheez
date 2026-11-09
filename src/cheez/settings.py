"""User settings: delivery time, languages, currency conversion, email.

Settings are layered, later layers winning:

1. built-in defaults (below);
2. a TOML file: ``$CHEEZ_CONFIG`` if set, else ``./cheez.toml`` in the
   repository root, else ``~/.config/cheez/cheez.toml``;
3. ``$CHEEZ_CONFIG_TOML``: the same TOML as text, for cloud environments where
   a file cannot be added (set it as an environment variable);
4. single-value overrides such as ``CHEEZ_EMAIL_TO`` (see ``ENV_OVERRIDES``).

``cheez.toml`` is gitignored because this repository is public; commit nothing
personal. ``cheez config init`` writes a commented starter file.
"""

from __future__ import annotations

import os
import tomllib
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import ROOT

LANGUAGES = {"en": "English", "zh-Hant": "繁體中文", "zh-Hans": "简体中文"}
Language = Literal["en", "zh-Hant", "zh-Hans"]

# Currencies offered for the "also show prices in" ruby annotation.
DISPLAY_CURRENCIES = ["USD", "GBP", "EUR", "HKD", "CNY", "TWD", "JPY", "SGD", "AUD", "CAD", "CHF", "KRW"]
CURRENCY_SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "HKD": "HK$", "CNY": "¥", "TWD": "NT$", "JPY": "¥",
                   "SGD": "S$", "AUD": "A$", "CAD": "C$", "CHF": "CHF ", "KRW": "₩"}
ZERO_DECIMAL = {"JPY", "KRW", "TWD"}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _currency(v: str) -> str:
    v = (v or "").strip().upper()
    if v in ("", "OFF", "NONE"):
        return ""
    if v not in DISPLAY_CURRENCIES:
        raise ValueError(f"currency must be one of {', '.join(DISPLAY_CURRENCIES)} (or empty for off)")
    return v


class Schedule(_M):
    deliver_at: str = "07:00"  # local time the brief should be ready
    timezone: str = "Europe/London"  # the reader's timezone; every time in the report uses it
    lead_minutes: int = Field(40, ge=10, le=180)  # a run takes about this long
    weekdays: str = "1-5"  # cron day-of-week field

    @field_validator("deliver_at")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        time.fromisoformat(v)
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        ZoneInfo(v)
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def city(self) -> str:
        return self.timezone.split("/")[-1].replace("_", " ")

    @property
    def deliver_time(self) -> time:
        return time.fromisoformat(self.deliver_at)

    def start_time(self) -> time:
        """When the scheduled run should start, kept off :00 and :30 (busy minutes)."""
        t = datetime.combine(date(2000, 1, 3), self.deliver_time) - timedelta(minutes=self.lead_minutes)
        if t.minute % 30 == 0:
            t -= timedelta(minutes=3)
        return t.time()

    def cron(self) -> str:
        s = self.start_time()
        return f"CRON_TZ={self.timezone} {s.minute} {s.hour} * * {self.weekdays}"

    def deliver_utc(self, d: date) -> datetime:
        return datetime.combine(d, self.deliver_time, tzinfo=self.tz).astimezone(ZoneInfo("UTC"))


class Report(_M):
    languages: list[Language] = Field(default_factory=lambda: ["en", "zh-Hant", "zh-Hans"])
    default_language: Language = "en"
    convert_to: str = ""  # "" = off; otherwise a DISPLAY_CURRENCIES code
    max_trades: int = Field(3, ge=1, le=6)

    @field_validator("convert_to")
    @classmethod
    def _cur(cls, v: str) -> str:
        return _currency(v)

    @field_validator("languages")
    @classmethod
    def _langs(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(["en", *v]))  # English is always written; it is what the validator checks


class Email(_M):
    enabled: bool = False
    to: list[str] = Field(default_factory=list)
    from_: str = Field("Cheez Daily <cheez@localhost>", alias="from")
    provider: Literal["smtp", "resend"] = "smtp"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_starttls: bool = True
    include_portfolio: bool = False
    language: str = ""  # empty: report.default_language
    convert_to: str = ""  # empty: report.convert_to
    page_url: str = ""  # link to the full private page
    subject_prefix: str = "Cheez Daily"

    @field_validator("convert_to")
    @classmethod
    def _cur(cls, v: str) -> str:
        return _currency(v)


class Publish(_M):
    artifact_url: str = ""  # the private claude.ai page Claude republishes each run


class Settings(_M):
    schedule: Schedule = Field(default_factory=Schedule)
    report: Report = Field(default_factory=Report)
    email: Email = Field(default_factory=Email)
    publish: Publish = Field(default_factory=Publish)
    source: list[str] = Field(default_factory=list, exclude=True)  # where values came from

    @property
    def email_language(self) -> str:
        lang = self.email.language or self.report.default_language
        return lang if lang in LANGUAGES else "en"

    @property
    def email_currency(self) -> str:
        return self.email.convert_to or self.report.convert_to


ENV_OVERRIDES = {
    "CHEEZ_DELIVER_AT": ("schedule", "deliver_at"),
    "CHEEZ_TIMEZONE": ("schedule", "timezone"),
    "CHEEZ_LANGUAGE": ("report", "default_language"),
    "CHEEZ_LANGUAGES": ("report", "languages"),
    "CHEEZ_CONVERT_TO": ("report", "convert_to"),
    "CHEEZ_EMAIL_TO": ("email", "to"),
    "CHEEZ_EMAIL_FROM": ("email", "from"),
    "CHEEZ_EMAIL_PROVIDER": ("email", "provider"),
    "CHEEZ_SMTP_HOST": ("email", "smtp_host"),
    "CHEEZ_SMTP_USER": ("email", "smtp_user"),
    "CHEEZ_PAGE_URL": ("email", "page_url"),
    "CHEEZ_ARTIFACT_URL": ("publish", "artifact_url"),
}
LIST_KEYS = {("report", "languages"), ("email", "to")}


def config_paths(env: Optional[dict] = None) -> list[Path]:
    env = os.environ if env is None else env
    if env.get("CHEEZ_CONFIG"):
        return [Path(env["CHEEZ_CONFIG"]).expanduser()]
    return [ROOT / "cheez.toml", Path("~/.config/cheez/cheez.toml").expanduser()]


def _merge(base: dict, extra: dict) -> dict:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load(env: Optional[dict] = None) -> Settings:
    env = dict(os.environ if env is None else env)
    data: dict = {}
    sources = ["defaults"]
    for p in config_paths(env):
        if p.is_file():
            _merge(data, tomllib.loads(p.read_text()))
            sources.append(str(p))
            break
    if env.get("CHEEZ_CONFIG_TOML"):
        _merge(data, tomllib.loads(env["CHEEZ_CONFIG_TOML"]))
        sources.append("$CHEEZ_CONFIG_TOML")
    for var, (sec, key) in ENV_OVERRIDES.items():
        if env.get(var):
            val: object = env[var]
            if (sec, key) in LIST_KEYS:
                val = [x.strip() for x in str(val).split(",") if x.strip()]
            data.setdefault(sec, {})[key] = val
            sources.append(f"${var}")
    s = Settings.model_validate(data)
    s.source = sources
    if s.email.enabled is False and env.get("CHEEZ_EMAIL_TO"):
        s.email.enabled = True  # setting a recipient by environment is an explicit opt-in
    return s


@lru_cache(maxsize=1)
def get() -> Settings:
    return load()


def reset() -> None:
    get.cache_clear()


STARTER = '''# Cheez settings. Copy to cheez.toml (gitignored) or set the whole text as the
# CHEEZ_CONFIG_TOML environment variable in your cloud environment.
# Every key is optional; the values shown are the defaults.

[schedule]
deliver_at = "07:00"           # when the brief should be ready, in your timezone
timezone = "Europe/London"     # your timezone; all times in the report use it
lead_minutes = 40              # a run takes about this long; the task starts this much earlier
weekdays = "1-5"               # cron day-of-week (Mon-Fri)

[report]
languages = ["en", "zh-Hant", "zh-Hans"]   # languages written each day; readers switch on the page
default_language = "en"        # en | zh-Hant | zh-Hans
convert_to = ""                # "" = off; or USD GBP EUR HKD CNY TWD JPY SGD AUD CAD CHF KRW
max_trades = 3                 # at most this many names in "Today's playbook"

[email]
enabled = false
to = []                        # e.g. ["you@example.com"]
from = "Cheez Daily <cheez@example.com>"
provider = "smtp"              # smtp (password in CHEEZ_SMTP_PASSWORD) | resend (key in CHEEZ_RESEND_API_KEY)
smtp_host = ""                 # e.g. "smtp.gmail.com" or "smtp.office365.com"
smtp_port = 587
smtp_user = ""
include_portfolio = false      # holdings stay out of your inbox unless you opt in
language = ""                  # "" = report.default_language
convert_to = ""                # "" = report.convert_to
page_url = ""                  # link to your private Cheez Daily page

[publish]
artifact_url = ""              # the private claude.ai page a Claude run republishes
'''
