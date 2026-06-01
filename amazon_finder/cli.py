"""Command-line interface for the Amazon product finder."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .finder import Criteria, find_products
from .output import render
from .rainforest import RainforestClient, RainforestError


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no external dependency) for the API key."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amazon-finder",
        description=(
            "Find Amazon products with strong recent monthly sales and multiple "
            "sellers (offers), using the Rainforest API."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    src = parser.add_argument_group("what to search")
    src.add_argument("-s", "--search", help="Search term / keyword, e.g. 'wireless earbuds'.")
    src.add_argument(
        "-c", "--category",
        dest="category_id",
        help="Rainforest category_id to browse instead of (or with) a search term.",
    )
    src.add_argument(
        "--domain", default="amazon.com",
        help="Amazon domain to query (amazon.com, amazon.co.uk, amazon.de, ...).",
    )
    src.add_argument(
        "--max-pages", type=int, default=1,
        help="How many search-result pages to scan.",
    )
    src.add_argument(
        "--sort-by",
        choices=["relevance", "price_low_to_high", "price_high_to_low",
                 "average_review", "most_recent", "featured"],
        help="Sort order for search results.",
    )

    crit = parser.add_argument_group("filter thresholds")
    crit.add_argument(
        "--min-sales", type=int, default=50,
        help="Minimum 'bought in past month' count (inclusive).",
    )
    crit.add_argument(
        "--min-offers", type=int, default=6,
        help="Minimum number of offers/sellers (inclusive). Default 6 = more than 5.",
    )
    crit.add_argument(
        "--no-check-offers", action="store_true",
        help="Skip the per-product offers lookup (faster/cheaper, no seller filter).",
    )

    out = parser.add_argument_group("output")
    out.add_argument(
        "-f", "--format", default="table", choices=["table", "csv", "json"],
        help="Output format.",
    )
    out.add_argument(
        "-o", "--output", help="Write results to a file instead of stdout.",
    )
    out.add_argument(
        "--quiet", action="store_true", help="Suppress progress messages on stderr.",
    )

    parser.add_argument(
        "--api-key", help="Rainforest API key (else RAINFOREST_API_KEY env / .env).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.search and not args.category_id:
        parser.error("provide a --search term and/or a --category id")

    _load_dotenv()
    api_key = args.api_key or os.environ.get("RAINFOREST_API_KEY", "")

    def progress(msg: str) -> None:
        if not args.quiet:
            print(msg, file=sys.stderr)

    try:
        client = RainforestClient(api_key, amazon_domain=args.domain)
        products = find_products(
            client,
            search_term=args.search,
            category_id=args.category_id,
            criteria=Criteria(
                min_sales=args.min_sales,
                min_offers=args.min_offers,
                check_offers=not args.no_check_offers,
            ),
            max_pages=args.max_pages,
            sort_by=args.sort_by,
            on_progress=progress,
        )
    except RainforestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    text = render(products, args.format)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        progress(f"Wrote {len(products)} products to {args.output}")
    else:
        print(text)

    return 0 if products else 1


if __name__ == "__main__":
    raise SystemExit(main())
