# amazon-finder

A small command-line **agent that finds suitable Amazon products** based on two
signals that matter for sourcing/reselling research:

1. **Recent monthly sales** — the *"X+ bought in past month"* badge Amazon shows
   on listings (default threshold: **≥ 50/month**).
2. **Number of offers (sellers)** — how many sellers compete on the listing
   (default threshold: **more than 5**, i.e. `--min-offers 6`).

Data comes from the [Rainforest API](https://www.rainforestapi.com/), which
returns Amazon search results and per-product offer data as clean JSON.
(Amazon's own APIs do **not** expose the "bought in past month" figure, which is
why a data provider is required.)

## How it works

```
search term ──▶ Rainforest search ──▶ parse "X+ bought in past month"
                                          │
                       drop anything below --min-sales   (no extra cost)
                                          │
              for survivors only: Rainforest offers lookup ──▶ count sellers
                                          │
                        keep products with ≥ --min-offers sellers
                                          ▼
                          table / CSV / JSON output
```

The two-stage filter is deliberate: the cheap sales filter runs first so the
billed per-product **offers** lookups only happen for products already worth
checking.

## Install

```bash
pip install -r requirements.txt        # just needs `requests`
# or install the CLI entry point:
pip install -e .
```

Requires Python 3.10+.

## Configure your API key

Get a key from Rainforest, then either export it or use a `.env` file:

```bash
export RAINFOREST_API_KEY=your_key_here
# or:
cp .env.example .env   # then edit .env
```

## Usage

```bash
# Default: ≥50 monthly sales AND more than 5 sellers
python -m amazon_finder --search "wireless earbuds"

# Browse a category, scan 3 result pages, write CSV
python -m amazon_finder --category 172282 --max-pages 3 \
    --format csv --output results.csv

# Stricter: ≥200/month and ≥10 sellers, on amazon.co.uk
python -m amazon_finder -s "yoga mat" --domain amazon.co.uk \
    --min-sales 200 --min-offers 10

# Skip the seller lookup (faster / cheaper, sales filter only)
python -m amazon_finder -s "garlic press" --no-check-offers
```

If installed via `pip install -e .`, use the `amazon-finder` command instead of
`python -m amazon_finder`.

### Key options

| Option | Default | Meaning |
| --- | --- | --- |
| `-s, --search` | — | Search keyword |
| `-c, --category` | — | Rainforest `category_id` to browse |
| `--min-sales` | `50` | Minimum "bought in past month" (inclusive) |
| `--min-offers` | `6` | Minimum sellers (inclusive; 6 = *more than 5*) |
| `--max-pages` | `1` | Search-result pages to scan |
| `--domain` | `amazon.com` | Amazon marketplace |
| `--sort-by` | — | `relevance`, `average_review`, `most_recent`, … |
| `--no-check-offers` | off | Skip per-product seller lookup |
| `-f, --format` | `table` | `table`, `csv`, or `json` |
| `-o, --output` | stdout | Write to a file |

You must provide a `--search` term and/or a `--category` id.

## Output

`table` (default) prints a compact terminal view; `csv`/`json` include every
field (ASIN, title, parsed monthly sales, raw badge text, offers count, price,
rating, review count, link, image).

Exit code is `0` when at least one product matched, `1` when none matched, and
`2` on an API error.

## Notes & limitations

- The "bought in past month" badge is a coarse, Amazon-supplied floor (`50+`,
  `1K+`, …). The tool parses it into an integer floor for comparison; it is not
  an exact sales count.
- Each product that passes the sales filter costs **one extra** Rainforest
  request for the offers lookup. Use `--no-check-offers` or a tighter
  `--min-sales` to control cost.
- Listings without a recent-sales badge are treated as *below threshold* and
  excluded.

## Development

```bash
python -m unittest discover -s tests -v
```

The parsing and filtering logic is fully unit-tested without any network calls
(`tests/test_sales.py`, `tests/test_finder.py`).
