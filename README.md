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

## Web dashboard

The same engine is exposed as a pastel, card-based web dashboard (this is what
gets deployed to Render):

```bash
# local dev server
python -m amazon_finder.web
# or production server (what Render runs):
gunicorn amazon_finder.web:app --bind 0.0.0.0:8000
```

Then open <http://localhost:8000>. Features:

- **Search** with the same filters as the CLI, shown as colourful product cards.
- **History** — every search (criteria + full results) is saved to SQLite so you
  can revisit a past run without spending another API call.
- **Settings** — change the dashboard passcode and the provider API key directly
  from the UI (stored in the DB, overriding the Blueprint env values).
- **Passcode gate** — if a passcode is configured, the dashboard requires it.

| Route | Purpose |
| --- | --- |
| `GET /` | Search form + results |
| `GET /history`, `GET /history/<id>` | Past searches and a saved result set |
| `GET /settings`, `POST /settings` | Change passcode / API key |
| `GET/POST /login`, `GET /logout` | Passcode gate |
| `GET /api/search` | JSON API, e.g. `/api/search?search=earbuds&min_sales=50&min_offers=6` |
| `GET /healthz` | Health check (reports provider, key + passcode status) |

Query params for `/` and `/api/search`: `search` (or `q`), `category`, `domain`,
`min_sales`, `min_offers`, `max_pages` (capped at 5), `check_offers` (`0`/`1`).

### Passcode protection

Set a passcode either via the **`ACCESS_CODE`** env var (Blueprint) or on the
**Settings** page (stored as a salted hash). When set, all routes except
`/login` and `/healthz` require the code. Sessions are signed with `SECRET_KEY`
(auto-generated on Render). With no passcode configured, the dashboard is open.

## Deploy on Render.com

This repo includes a [`render.yaml`](render.yaml) Blueprint, so deploying is a
few clicks:

1. Push this repo to GitHub (already done if you're reading this there).
2. In Render: **New + → Blueprint**, and select this repository. Render reads
   `render.yaml` and provisions a free **Web Service** that runs
   `gunicorn amazon_finder.web:app`.
3. When prompted (or under **Environment**), set the secrets:
   - **`RAPIDAPI_KEY`** — your RapidAPI key (or set it later in Settings).
   - **`ACCESS_CODE`** — the dashboard passcode (or set it later in Settings).
   `PROVIDER` defaults to `rapidapi` and `SECRET_KEY` is auto-generated.
4. Deploy. Render gives you a URL like `https://amazon-product-finder.onrender.com`;
   open it to use the dashboard, or call `/api/search` for JSON.

> **History persistence:** search history and UI-set settings live in a SQLite
> file (`HISTORY_DB`). Render's **free** tier has an ephemeral filesystem, so
> they reset on each deploy/restart. To keep them, upgrade the plan and attach a
> persistent disk (see the commented `disk:` block in `render.yaml`).

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
