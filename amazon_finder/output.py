"""Rendering matched products as a table, CSV, or JSON."""

from __future__ import annotations

import csv
import io
import json
from typing import Sequence

from .models import Product, OUTPUT_FIELDS


def to_json(products: Sequence[Product], *, indent: int = 2) -> str:
    return json.dumps([p.as_row() for p in products], indent=indent, ensure_ascii=False)


def to_csv(products: Sequence[Product]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for product in products:
        writer.writerow(product.as_row())
    return buf.getvalue()


def _truncate(text: str, width: int) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def to_table(products: Sequence[Product]) -> str:
    """Compact human-readable table for the terminal."""
    if not products:
        return "No products matched the criteria."

    header = f"{'ASIN':<12} {'SALES/mo':>9} {'OFFERS':>7}  {'PRICE':>10}  TITLE"
    lines = [header, "-" * len(header)]
    for p in products:
        sales = f"{p.recent_sales}+" if p.recent_sales is not None else "?"
        offers = str(p.offers_count) if p.offers_count is not None else "?"
        price = f"{p.currency}{p.price}" if p.price is not None else "-"
        lines.append(
            f"{p.asin:<12} {sales:>9} {offers:>7}  {price:>10}  {_truncate(p.title, 60)}"
        )
    return "\n".join(lines)


def render(products: Sequence[Product], fmt: str) -> str:
    fmt = fmt.lower()
    if fmt == "json":
        return to_json(products)
    if fmt == "csv":
        return to_csv(products)
    if fmt == "table":
        return to_table(products)
    raise ValueError(f"Unknown output format: {fmt!r}")
