# amazon-finder

An **agent that finds suitable Amazon products** based on two signals that
matter for sourcing/reselling research. It runs as a **command-line tool** *and*
as a **web service you can deploy to [Render.com](https://render.com)** (see
[Deploy on Render](#deploy-on-rendercom)).

1. **Recent monthly sales** — the *"X+ bought in past month"* badge Amazon shows
   on listings (default threshold: **≥ 50/month**).
2. **Number of offers (sellers)** — how many sellers compete on the listing
   (default threshold: **more than 5**, i.e. `--min-offers 6`).

Amazon's own APIs do **not** expose the "bought in past month" figure, so a data
provider is required. The data source is **pluggable** (`--provider`):

| Provider | Default | Notes |
| --- | --- | --- |
| **`rapidapi`** | ✅ | [Real-Time Amazon Data](https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-amazon-data) on RapidAPI. Has a **free Basic plan**. Returns `sales_volume` + `product_num_offers` in one call. |
| `rainforest` | | [Rainforest API](https://www.rainforestapi.com/). Paid. Kept for compatibility. |

Set the key for whichever provider you pick (`RAPIDAPI_KEY` or
`RAINFOREST_API_KEY`).

## How it works

```
search term ──▶ provider search ──▶ parse "X+ bought in past month"
                                          │              + offers count
                                          ▼
                  keep products with ≥ --min-sales AND ≥ --min-offers
                                          ▼
                          table / CSV / JSON output
```

With the default **RapidAPI** provider, each result already carries both the
sales badge and the offer count, so one request per page covers everything.
(The `rainforest` provider instead does a cheap sales pre-filter first, then a
billed per-product offers lookup only for the survivors.)

## Install

```bash
pip install -r requirements.txt
# or install the CLI entry point:
pip install -e .
```

Requires Python 3.10+.

## Configure your API key

Default provider is **RapidAPI**. Subscribe (free Basic plan) to
[Real-Time Amazon Data](https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-amazon-data),
copy your RapidAPI key, then either export it or use a `.env` file:

```bash
export RAPIDAPI_KEY=your_key_here
# or:
cp .env.example .env   # then edit .env
```

To use Rainforest instead: set `RAINFOREST_API_KEY` and pass `--provider rainforest`
(CLI) or `PROVIDER=rainforest` (web).

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
| `-c, --category` | — | Category id to browse |
| `--provider` | `rapidapi` | Data backend: `rapidapi` or `rainforest` |
| `--min-sales` | `50` | Minimum "bought in past month" (inclusive) |
| `--min-offers` | `6` | Minimum sellers (inclusive; 6 = *more than 5*) |
| `--max-pages` | `1` | Search-result pages to scan |
| `--domain` | `amazon.com` | Amazon marketplace |
| `--sort-by` | — | `relevance`, `average_review`, `most_recent`, … |
| `--no-check-offers` | off | Skip per-product seller lookup |
| `-f, --format` | `table` | `table`, `csv`, or `json` |
| `-o, --output` | stdout | Write to a file |

You must provide a `--search` term and/or a `--category` id.

## Web service

The same engine is exposed over HTTP so you can use it from a browser (this is
what gets deployed to Render):

```bash
# local dev server
python -m amazon_finder.web
# or production server (what Render runs):
gunicorn amazon_finder.web:app --bind 0.0.0.0:8000
```

Then open <http://localhost:8000>. Endpoints:

| Route | Purpose |
| --- | --- |
| `GET /` | HTML search form + results table |
| `GET /api/search` | JSON API, e.g. `/api/search?search=earbuds&min_sales=50&min_offers=6` |
| `GET /healthz` | Health check (also reports whether the API key is configured) |

Query params for `/` and `/api/search`: `search` (or `q`), `category`, `domain`,
`min_sales`, `min_offers`, `max_pages` (capped at 5), `check_offers` (`0`/`1`).

## Deploy on Render.com

This repo includes a [`render.yaml`](render.yaml) Blueprint, so deploying is a
few clicks:

1. Push this repo to GitHub (already done if you're reading this there).
2. In Render: **New + → Blueprint**, and select this repository. Render reads
   `render.yaml` and provisions a free **Web Service** that runs
   `gunicorn amazon_finder.web:app`.
3. When prompted (or under **Environment**), set the secret
   **`RAPIDAPI_KEY`** to your key. It's declared with `sync: false` so it is
   never committed — you supply it in the dashboard. (`PROVIDER` defaults to
   `rapidapi` in `render.yaml`.)
4. Deploy. Render gives you a URL like `https://amazon-product-finder.onrender.com`;
   open it to use the search form, or call `/api/search` for JSON.

Render auto-detects the port via `$PORT`, and `/healthz` is configured as the
health check. Prefer not to use the Blueprint? Create a **Web Service** manually
with build command `pip install -r requirements.txt` and the start command from
the [`Procfile`](Procfile).

> **Note:** Render's free web services sleep after inactivity, so the first
> request after idle can take ~30–60s to wake. Each search also makes live API
> calls that count against your provider's monthly quota (the RapidAPI free
> Basic plan has a limited number of requests).

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
- With the `rainforest` provider, each product that passes the sales filter
  costs **one extra** request for the offers lookup; use `--no-check-offers` or
  a tighter `--min-sales` to control cost. The default `rapidapi` provider
  returns offers inline, so this doesn't apply.
- Listings without a recent-sales badge are treated as *below threshold* and
  excluded.

## Development

```bash
python -m unittest discover -s tests -v
```

The parsing and filtering logic is fully unit-tested without any network calls
(`tests/test_sales.py`, `tests/test_finder.py`).
