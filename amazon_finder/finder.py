"""Core search-and-filter logic, independent of the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import Product
from .rainforest import RainforestClient
from .sales import parse_recent_sales


@dataclass
class Criteria:
    """Thresholds a product must meet to be considered suitable."""

    min_sales: int = 50
    min_offers: int = 5
    check_offers: bool = True


def matches(product: Product, criteria: Criteria) -> bool:
    """True if a fully-populated product clears the criteria.

    Unknown values never pass: a missing sales badge or offer count is treated
    as below threshold. ``check_offers=False`` skips the seller requirement.
    """
    if product.recent_sales is None or product.recent_sales < criteria.min_sales:
        return False
    if criteria.check_offers and (
        product.offers_count is None or product.offers_count < criteria.min_offers
    ):
        return False
    return True


def product_from_search_result(result: dict) -> Product:
    """Build a :class:`Product` from one Rainforest search-result entry."""
    price = result.get("price") or {}
    recent_sales_text = (
        result.get("recent_sales")
        or result.get("bought_past_month")
        or ""
    )
    return Product(
        asin=result.get("asin", ""),
        title=result.get("title", ""),
        link=result.get("link", ""),
        image=result.get("image", ""),
        price=price.get("value") if isinstance(price, dict) else None,
        currency=price.get("currency", "") if isinstance(price, dict) else "",
        rating=result.get("rating"),
        ratings_total=result.get("ratings_total"),
        recent_sales_text=recent_sales_text,
        recent_sales=parse_recent_sales(recent_sales_text),
    )


def find_products(
    client: RainforestClient,
    *,
    search_term: str | None = None,
    category_id: str | None = None,
    criteria: Criteria | None = None,
    max_pages: int = 1,
    sort_by: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[Product]:
    """Search Amazon and return products meeting ``criteria``.

    Strategy (to keep API usage / cost down):
      1. Page through search results, parse the recent-sales badge.
      2. Drop anything below ``min_sales`` before spending any offers requests.
      3. Only for survivors, fetch the offers count and apply ``min_offers``.
    """
    criteria = criteria or Criteria()

    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    # Stage 1+2: search and pre-filter on sales (no extra API cost).
    sales_passed: list[Product] = []
    seen: set[str] = set()
    scanned = 0
    for result in client.iter_search_results(
        search_term, category_id=category_id, max_pages=max_pages, sort_by=sort_by
    ):
        scanned += 1
        product = product_from_search_result(result)
        if not product.asin or product.asin in seen:
            continue
        seen.add(product.asin)
        if product.recent_sales is not None and product.recent_sales >= criteria.min_sales:
            sales_passed.append(product)

    log(
        f"Scanned {scanned} results; {len(sales_passed)} clear "
        f">= {criteria.min_sales} monthly sales."
    )

    if not criteria.check_offers:
        return sales_passed

    # Stage 3: enrich survivors with offers count, filter on min_offers.
    matched: list[Product] = []
    for i, product in enumerate(sales_passed, start=1):
        log(f"Checking offers {i}/{len(sales_passed)}: {product.asin}")
        product.offers_count = client.offers_count(product.asin)
        if matches(product, criteria):
            matched.append(product)

    log(f"{len(matched)} products clear > {criteria.min_offers - 1} offers.")
    return matched
