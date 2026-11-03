"""HTTP access with bounded retries, a per-run request budget and a small disk cache.

Every network call in the deterministic pipeline goes through ``Fetcher`` so a
provider outage or rate limit degrades one section instead of hanging the run.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests

USER_AGENT = "Mozilla/5.0 (compatible; cheez/0.1; personal research)"


class BudgetExhausted(RuntimeError):
    pass


class FetchError(RuntimeError):
    pass


@dataclass
class Fetcher:
    cache_dir: Optional[Path] = None
    max_requests: int = 400
    max_attempts: int = 3
    timeout: float = 20.0
    backoff: float = 1.5
    offline: bool = False  # when True only the cache is used (tests, demo)
    requests_made: int = 0
    errors: list[str] = field(default_factory=list)
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
        ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
        if not ca and Path("/root/.ccr/ca-bundle.crt").exists():
            # Cloud sessions route HTTPS through a proxy with its own CA bundle.
            self.session.verify = "/root/.ccr/ca-bundle.crt"
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url: str, params: Optional[dict]) -> Optional[Path]:
        if not self.cache_dir:
            return None
        key = url + "?" + json.dumps(params or {}, sort_keys=True)
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:32] + ".cache")

    def get(
        self,
        url: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        max_age: float = 600.0,
    ) -> bytes:
        cp = self._cache_path(url, params)
        if cp and cp.exists() and (self.offline or time.time() - cp.stat().st_mtime < max_age):
            return cp.read_bytes()
        if self.offline:
            raise FetchError(f"offline and not cached: {url}")
        last_err: Optional[str] = None
        for attempt in range(1, self.max_attempts + 1):
            if self.requests_made >= self.max_requests:
                raise BudgetExhausted(f"request budget of {self.max_requests} exhausted")
            self.requests_made += 1
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = f"HTTP {r.status_code}"
                    retry_after = r.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else self.backoff**attempt
                    time.sleep(min(wait, 10.0))
                    continue
                if r.status_code >= 400:
                    raise FetchError(f"HTTP {r.status_code} for {url}")
                if cp:
                    cp.write_bytes(r.content)
                return r.content
            except requests.RequestException as e:  # network error: retry
                last_err = type(e).__name__
                time.sleep(min(self.backoff**attempt, 10.0))
        msg = f"giving up on {url}: {last_err}"
        self.errors.append(msg)
        raise FetchError(msg)

    def get_json(self, url: str, params: Optional[dict] = None, **kw: Any) -> Any:
        return json.loads(self.get(url, params=params, **kw))
