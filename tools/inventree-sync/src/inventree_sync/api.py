"""Read-only HTTP transport with typed iterators and complete pagination."""

from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import time
from typing import TypeVar
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from requests.auth import HTTPBasicAuth

from . import adapters
from .config import ConfigError, InvenTreeSettings, read_token
from .models import Category, Parameter, ParameterTemplate, Part, PartWithParameters

logger = logging.getLogger(__name__)
T = TypeVar("T", Category, Part, ParameterTemplate, Parameter, PartWithParameters)
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class APIError(RuntimeError):
    """Transport, authentication or pagination failed; data is incomplete."""


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    if retry_after:
        try:
            if retry_after.isdigit():
                delay = float(retry_after)
            else:
                target = parsedate_to_datetime(retry_after)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                delay = max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
            if delay > 60:
                raise APIError("Server requests a retry delay above 60 seconds; retry this run later")
            return delay
        except (ValueError, TypeError, OverflowError):
            pass
    return float(2 ** min(attempt, 5))


class InvenTreeClient:
    """Use as a context manager; consume iterators fully before using a dataset.

    Supports the modern wire contract in adapters.py, not every InvenTree release.
    Basic credentials are supplied explicitly; token mode is legacy opt-in.
    """

    def __init__(self, settings: InvenTreeSettings, auth: HTTPBasicAuth | None = None):
        self.settings = settings
        if settings.auth == "basic":
            if not isinstance(auth, HTTPBasicAuth) or not isinstance(auth.username, str) or not auth.username.strip() or ":" in auth.username:
                raise ConfigError("Basic Authentication requires a nonempty username without a colon")
            if not isinstance(auth.password, str) or not auth.password:
                raise ConfigError("Basic Authentication requires a nonempty password")
            try:
                auth.username.encode("latin-1")
                auth.password.encode("latin-1")
            except UnicodeError:
                raise ConfigError("Credentials cannot be encoded by Requests HTTPBasicAuth") from None
            self._auth = auth
            self._headers = {}
        else:
            if auth is not None:
                raise ConfigError("Do not supply Basic credentials with token authentication")
            self._auth = None
            self._headers = {"Authorization": f"Token {read_token(settings)}"}
        self._api_root = settings.base_url.rstrip("/") + "/api/"
        self._session = requests.Session()
        # Avoid implicit .netrc authentication, cookies and environment TLS overrides.
        self._session.trust_env = False

    def __enter__(self) -> "InvenTreeClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()
        self._auth = None
        self._headers.clear()

    def iter_categories(self) -> Iterator[Category]:
        return self._iterate(adapters.CATEGORIES_ENDPOINT, adapters.category)

    def iter_parts(self) -> Iterator[Part]:
        """Unfiltered diagnostic endpoint; never used by the export workflow."""
        return self._iterate(adapters.PARTS_ENDPOINT, adapters.part)

    def iter_parts_with_parameters(self, category_pk: int) -> Iterator[PartWithParameters]:
        """Read only the requested subtree, with actual parameters and templates."""
        if type(category_pk) is not int or category_pk <= 0:
            raise ValueError("category_pk must be a positive integer PK")
        return self._iterate(
            adapters.PARTS_ENDPOINT,
            adapters.part_with_parameters,
            {"category": str(category_pk), "cascade": "true", "parameters": "true"},
        )

    def iter_parameter_templates(self) -> Iterator[ParameterTemplate]:
        return self._iterate(adapters.TEMPLATES_ENDPOINT, adapters.parameter_template)

    def iter_part_parameters(self) -> Iterator[Parameter]:
        return self._iterate(
            adapters.PARAMETERS_ENDPOINT, adapters.parameter,
            {"model_type": adapters.PART_MODEL_TYPE},
        )

    def _get_json(self, url: str, endpoint: str) -> object:
        for attempt in range(self.settings.retries + 1):
            try:
                response = self._session.get(
                    url,
                    headers=dict(self._headers),
                    auth=self._auth,
                    timeout=(self.settings.connect_timeout, self.settings.read_timeout),
                    verify=True,
                    allow_redirects=False,
                )
            except requests.Timeout:
                raise APIError(f"GET {endpoint}: request timed out") from None
            except requests.ConnectionError:
                raise APIError(f"GET {endpoint}: connection or TLS failure") from None
            except requests.RequestException:
                raise APIError(f"GET {endpoint}: HTTP transport failure") from None
            try:
                status = response.status_code
                if status == 401:
                    challenge = response.headers.get("WWW-Authenticate", "")
                    if isinstance(challenge, str) and challenge.lower().startswith(("digest ", "negotiate", "bearer ")) and self.settings.auth == "basic":
                        raise APIError(f"GET {endpoint}: HTTP 401, server requires an authentication method unsupported by Basic mode")
                    raise APIError(f"GET {endpoint}: HTTP 401, authentication failed. Check your username and password (or legacy token); confirm the server permits the selected authentication method.")
                if status == 403:
                    raise APIError(f"GET {endpoint}: HTTP 403, insufficient permissions for this operation")
                if status in _RETRY_STATUSES and attempt < self.settings.retries:
                    delay = _retry_delay(response.headers.get("Retry-After"), attempt)
                elif status != 200:
                    # Never display response bodies, redirect locations or request headers.
                    raise APIError(f"GET {endpoint}: HTTP {status}; no complete dataset available")
                else:
                    try:
                        return response.json()
                    except ValueError:
                        raise APIError(f"GET {endpoint}: malformed JSON") from None
            finally:
                response.close()
                self._session.cookies.clear()
            logger.warning("GET %s: HTTP %d; retry %d", endpoint, status, attempt + 1)
            time.sleep(delay)
        raise AssertionError("Retry loop exhausted unexpectedly")

    def _page_url(
        self, value: str, current: str, endpoint: str, filters: dict[str, str]
    ) -> str:
        """Restrict pagination to this exact collection inside the configured API."""
        try:
            if any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value:
                raise ValueError
            raw_path = urlsplit(value).path
            if "%" in raw_path or any(p in {".", ".."} for p in raw_path.split("/")):
                raise ValueError
            resolved = urlsplit(urljoin(current, value))
            expected = urlsplit(self._api_root + endpoint)
            origin = lambda u: (u.scheme, u.hostname, u.port or (443 if u.scheme == "https" else 80))
            if (
                origin(resolved) != origin(expected)
                or resolved.username is not None or resolved.password is not None
                or resolved.fragment or "#" in value
                or resolved.path != expected.path
            ):
                raise ValueError
            query = parse_qsl(resolved.query, keep_blank_values=True)
            for key, val in filters.items():
                if [v for k, v in query if k == key] != [val]:
                    raise ValueError
            # Canonical query ordering catches repeated URLs with reordered parameters.
            return urlunsplit((expected.scheme, expected.netloc, expected.path,
                               urlencode(sorted(query)), ""))
        except ValueError:
            raise APIError(f"GET {endpoint}: unsafe or invalid pagination URL") from None

    def _iterate(
        self, endpoint: str, convert: Callable[[object], T],
        filters: dict[str, str] | None = None,
    ) -> Iterator[T]:
        filters = filters or {}
        initial = self._api_root + endpoint
        if filters:
            initial += "?" + urlencode(filters)
        url: str | None = self._page_url(initial, initial, endpoint, filters)
        visited: set[str] = set()
        seen_pks: set[int] = set()
        total: int | None = None
        paginated: bool | None = None
        while url is not None:
            if url in visited:
                raise APIError(f"GET {endpoint}: repeated/cyclic pagination")
            visited.add(url)
            payload = self._get_json(url, endpoint)
            is_page = isinstance(payload, dict)
            if paginated is not None and paginated != is_page:
                raise APIError(f"GET {endpoint}: pagination response shape changed")
            paginated = is_page
            next_value = None
            if isinstance(payload, list):
                records = payload
            elif isinstance(payload, dict) and "results" in payload and "next" in payload:
                records = payload["results"]
                next_value = payload["next"]
                if not isinstance(records, list) or (
                    next_value is not None and (not isinstance(next_value, str) or not next_value)
                ):
                    raise APIError(f"GET {endpoint}: malformed pagination fields")
                if "count" in payload:
                    count = payload["count"]
                    if type(count) is not int or count < 0 or (total is not None and count != total):
                        raise APIError(f"GET {endpoint}: invalid/changing pagination count")
                    total = count
            else:
                raise APIError(f"GET {endpoint}: unsupported list response structure")
            if not records and next_value is not None:
                raise APIError(f"GET {endpoint}: empty page with a continuation")
            next_url = self._page_url(next_value, url, endpoint, filters) if next_value else None
            for record in records:
                item = convert(record)
                if item.pk in seen_pks:
                    raise APIError(f"GET {endpoint}: repeated object pk={item.pk}")
                seen_pks.add(item.pk)
                yield item
            if total is not None and (len(seen_pks) > total or (next_url is None and len(seen_pks) != total)):
                raise APIError(f"GET {endpoint}: incomplete/inconsistent pagination count")
            url = next_url

