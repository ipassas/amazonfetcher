"""Thin client around the Rainforest API (https://www.rainforestapi.com/).

Only the two request types this tool needs are implemented:

* ``type=search``  -> a page of search results (incl. the ``recent_sales`` badge)
* ``type=offers``  -> the list/count of sellers (offers) for one ASIN
"""

from __future__ import annotations

import time
from typing import Iterator

import requests

BASE_URL = "https://api.rainforestapi.com/request"


class RainforestError(RuntimeError):
    """Raised when the Rainforest API returns an error or invalid response."""


class RainforestClient:
    def __init__(
        self,
        api_key: str,
        amazon_domain: str = "amazon.com",
        *,
        timeout: int = 60,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ):
        if not api_key:
            raise RainforestError(
                "No Rainforest API key provided. Set RAINFOREST_API_KEY or pass --api-key."
            )
        self.api_key = api_key
        self.amazon_domain = amazon_domain
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()

    # -- low level ---------------------------------------------------------
    def _get(self, params: dict) -> dict:
        """GET with simple exponential-backoff retry on transient failures."""
        params = {"api_key": self.api_key, "amazon_domain": self.amazon_domain, **params}
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(BASE_URL, params=params, timeout=self.timeout)
            except requests.RequestException as exc:  # network-level failure
                last_error = exc
            else:
                # 429/5xx are worth retrying; 4xx (bad request/auth) are not.
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise RainforestError("Rainforest returned non-JSON response") from exc
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = RainforestError(
                        f"Rainforest API returned HTTP {resp.status_code}"
                    )
                else:
                    raise RainforestError(
                        f"Rainforest API error HTTP {resp.status_code}: {resp.text[:300]}"
                    )

            if attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s, ...

        raise RainforestError(f"Rainforest request failed after retries: {last_error}")

    # -- high level --------------------------------------------------------
    def search(
        self,
        search_term: str | None = None,
        *,
        category_id: str | None = None,
        page: int = 1,
        sort_by: str | None = None,
    ) -> dict:
        """One page of Amazon search results."""
        params: dict = {"type": "search", "page": page}
        if search_term:
            params["search_term"] = search_term
        if category_id:
            params["category_id"] = category_id
        if sort_by:
            params["sort_by"] = sort_by
        if not search_term and not category_id:
            raise RainforestError("search() requires either a search_term or a category_id")
        return self._get(params)

    def iter_search_results(
        self,
        search_term: str | None = None,
        *,
        category_id: str | None = None,
        max_pages: int = 1,
        sort_by: str | None = None,
    ) -> Iterator[dict]:
        """Yield raw search-result dicts across up to ``max_pages`` pages."""
        for page in range(1, max_pages + 1):
            data = self.search(
                search_term, category_id=category_id, page=page, sort_by=sort_by
            )
            results = data.get("search_results") or []
            if not results:
                break
            yield from results

    def offers_count(self, asin: str) -> int | None:
        """Number of distinct offers (sellers) for an ASIN, or ``None``.

        Prefers the API's reported total; falls back to counting the offers
        array on the first page (enough to evaluate small thresholds).
        """
        data = self._get({"type": "offers", "asin": asin})

        pagination = data.get("pagination") or {}
        total = pagination.get("total_results")
        if isinstance(total, int) and total > 0:
            return total

        offers = data.get("offers")
        if isinstance(offers, list):
            return len(offers)
        return None
