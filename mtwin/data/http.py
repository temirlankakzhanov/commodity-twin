"""HTTP client with retries, exponential back-off and secret-safe error messages."""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from mtwin.config import Settings
from mtwin.data.errors import ProviderError

RETRY_STATUSES = (429, 500, 502, 503, 504)


def build_session(settings: Settings) -> requests.Session:
    """Create a ``requests`` session that retries transient failures.

    Connection errors, read timeouts and the statuses in :data:`RETRY_STATUSES` are retried
    with exponential back-off; ``Retry-After`` headers are honoured.
    """
    retry = Retry(
        total=settings.http_retries,
        connect=settings.http_retries,
        read=settings.http_retries,
        status=settings.http_retries,
        backoff_factor=settings.http_backoff_s,
        status_forcelist=RETRY_STATUSES,
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": settings.user_agent,
            "Accept": "application/json, text/csv;q=0.9, */*;q=0.5",
        }
    )
    return session


def _safe_url(url: str) -> str:
    """Drop the query string so API keys can never leak into messages."""
    return url.split("?", 1)[0]


class HttpClient:
    """Thin wrapper that turns every failure into :class:`ProviderError`.

    Error messages contain the URL *without* its query string and the exception class name
    only, because exception texts raised by ``requests`` may embed the full request URL.
    """

    def __init__(self, settings: Settings, session: Any | None = None) -> None:
        self._session = session if session is not None else build_session(settings)
        self._timeout = settings.http_timeout_s

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        """GET ``url`` and return the response body as text."""
        return self._request(url, params).text

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``url`` and decode the JSON body."""
        response = self._request(url, params)
        try:
            return response.json()
        except ValueError:
            raise ProviderError(f"Invalid JSON returned by {_safe_url(url)}") from None

    def _request(self, url: str, params: dict[str, Any] | None) -> Any:
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"GET {_safe_url(url)} failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise ProviderError(f"GET {_safe_url(url)} returned HTTP {response.status_code}")
        return response
