"""Data structures describing a candidate Amazon product."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field


@dataclass
class Product:
    """A single Amazon product evaluated against the search criteria."""

    asin: str
    title: str
    link: str = ""
    image: str = ""
    price: float | None = None
    currency: str = ""
    rating: float | None = None
    ratings_total: int | None = None

    # Raw "X+ bought in past month" badge text, plus its parsed integer floor.
    recent_sales_text: str = ""
    recent_sales: int | None = None

    # Number of offers (distinct sellers) for the product.
    offers_count: int | None = None

    def as_row(self) -> dict:
        """Flat, serialisable dict suitable for CSV/JSON output."""
        return asdict(self)

    @property
    def is_complete(self) -> bool:
        """True once both signals we filter on are known."""
        return self.recent_sales is not None and self.offers_count is not None


# Standard column order for tabular/CSV output.
OUTPUT_FIELDS = [
    "asin",
    "title",
    "recent_sales",
    "recent_sales_text",
    "offers_count",
    "price",
    "currency",
    "rating",
    "ratings_total",
    "link",
    "image",
]
