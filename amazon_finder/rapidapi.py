"""Data provider backed by the "Real-Time Amazon Data" API on RapidAPI.

https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-amazon-data

Why this one: its ``/search`` endpoint returns, for every product, both the
``sales_volume`` badge ("X+ bought in past month") *and* ``product_num_offers``
in a single response — so one request per page covers both of our filters, and
it has a free Basic plan.
"""

from __future__ import annotations

import re
import time
from typing import Iterator

import requests

from .errors import ProviderError
from .models import Product
from .sales import parse_recent_sales

DEFAULT_HOST = "real-time-amazon-data.p.rapidapi.com"

# Map an Amazon domain to the API's two-letter country code.
COUNTRY_BY_DOMAIN = {
    "amazon.com": "US",
    "amazon.co.uk": "UK",
    "amazon.de": "DE",
    "amazon.fr": "FR",
    "amazon.co.jp": "JP",
    "amazon.ca": "CA",
    "amazon.it": "IT",
    "amazon.es": "ES",
    "amazon.in": "IN",
    "amazon.com.mx": "MX",
    "amazon.com.br": "BR",
    "amazon.com.au": "AU",
    "amazon.nl": "NL",
    "amazon.sg": "SG",
    "amazon.ae": "AE",
    "amazon.sa": "SA",
}

# Map our CLI sort-by vocabulary to this API's sort_by values.
SORT_MAP = {
    "relevance": "RELEVANCE",
    "price_low_to_high": "LOWEST_PRICE",
    "price_high_to_low": "HIGHEST_PRICE",
    "average_review": "REVIEWS",
    "most_recent": "NEWEST",
    "featured": "RELEVANCE",
}

_NUMBER_RE = re.compile(r"\d+\.?\d*")


class RapidApiError(ProviderError):
    """Raised when the RapidAPI endpoint errors or returns an invalid response."""


def _parse_price(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUMBER_RE.search(value.replace(",", ""))
    return float(match.group()) if match else None


def _parse_float(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUMBER_RE.search(value.replace(",", ""))
    return float(match.group()) if match else None


def _parse_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\d[\d,]*", value)
        if match:
            return int(match.group().replace(",", ""))
    return None


def product_from_result(result: dict) -> Product:
    """Map one RapidAPI search-result entry to a :class:`Product`."""
    sales_text = result.get("sales_volume") or ""
    return Product(
        asin=result.get("asin", "") or "",
        title=result.get("product_title", "") or "",
        link=result.get("product_url", "") or "",
        image=result.get("product_photo", "") or "",
        price=_parse_price(result.get("product_price")),
        currency=result.get("currency", "") or "",
        rating=_parse_float(result.get("product_star_rating")),
        ratings_total=_parse_int(result.get("product_num_ratings")),
        recent_sales_text=sales_text,
        recent_sales=parse_recent_sales(sales_text),
        offers_count=_parse_int(result.get("product_num_offers")),
    )


class RapidApiClient:
    def __init__(
        self,
        api_key: str,
        amazon_domain: str = "amazon.com",
        *,
        host: str = DEFAULT_HOST,
        timeout: int = 60,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ):
        if not api_key:
            raise RapidApiError(
                "No RapidAPI key provided. Set RAPIDAPI_KEY or pass --api-key."
            )
        self.api_key = api_key
        self.host = host
        self.country = COUNTRY_BY_DOMAIN.get(amazon_domain.lower(), "US")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict) -> dict:
        headers = {"X-RapidAPI-Key": self.api_key, "X-RapidAPI-Host": self.host}
        url = f"https://{self.host}{path}"
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise RapidApiError("RapidAPI returned non-JSON response") from exc
                if resp.status_code == 429:
                    last_error = RapidApiError(
                        "RapidAPI rate limit / monthly quota exceeded (HTTP 429)"
                    )
                elif resp.status_code in (500, 502, 503, 504):
                    last_error = RapidApiError(f"RapidAPI server error HTTP {resp.status_code}")
                else:
                    raise RapidApiError(
                        f"RapidAPI error HTTP {resp.status_code}: {resp.text[:300]}"
                    )

            if attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)

        raise RapidApiError(f"RapidAPI request failed after retries: {last_error}")

    def search(
        self,
        query: str | None = None,
        *,
        category_id: str | None = None,
        page: int = 1,
        sort_by: str | None = None,
    ) -> list[dict]:
        """One page of results. Uses /search for keywords, /products-by-category otherwise."""
        params: dict = {"country": self.country, "page": page}
        if sort_by:
            mapped = SORT_MAP.get(sort_by)
            if mapped:
                params["sort_by"] = mapped

        if query:
            path = "/search"
            params["query"] = query
            if category_id:
                params["category_id"] = category_id
        elif category_id:
            path = "/products-by-category"
            params["category_id"] = category_id
        else:
            raise RapidApiError("search requires a query or a category_id")

        data = self._get(path, params)
        return ((data or {}).get("data") or {}).get("products") or []

    def iter_search_results(
        self,
        query: str | None = None,
        *,
        category_id: str | None = None,
        max_pages: int = 1,
        sort_by: str | None = None,
    ) -> Iterator[dict]:
        for page in range(1, max_pages + 1):
            products = self.search(
                query, category_id=category_id, page=page, sort_by=sort_by
            )
            if not products:
                break
            yield from products


def find_products_rapidapi(
    client: RapidApiClient,
    *,
    search_term: str | None = None,
    category_id: str | None = None,
    criteria=None,
    max_pages: int = 1,
    sort_by: str | None = None,
    on_progress=None,
) -> list[Product]:
    """Search via RapidAPI and return products meeting ``criteria``.

    Both signals (sales + offers) arrive in the search response, so unlike the
    Rainforest path there is no per-product follow-up request.
    """
    from .finder import Criteria, matches  # local import avoids an import cycle

    criteria = criteria or Criteria()

    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    matched: list[Product] = []
    seen: set[str] = set()
    scanned = 0
    for result in client.iter_search_results(
        search_term, category_id=category_id, max_pages=max_pages, sort_by=sort_by
    ):
        scanned += 1
        product = product_from_result(result)
        if not product.asin or product.asin in seen:
            continue
        seen.add(product.asin)
        if matches(product, criteria):
            matched.append(product)

    log(f"Scanned {scanned} results; {len(matched)} meet the criteria.")
    return matched
