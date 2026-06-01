"""Flask web service wrapper around the product finder.

Exposes:
  GET /            HTML search form + results table
  GET /api/search  JSON API (same params as the form)
  GET /healthz     health check for Render

Run locally:   python -m amazon_finder.web
On Render:     gunicorn amazon_finder.web:app --bind 0.0.0.0:$PORT
"""

from __future__ import annotations

import os

from flask import Flask, request, jsonify, Response

from .finder import Criteria, find_products
from .rainforest import RainforestClient, RainforestError

app = Flask(__name__)

# Cap pages so a single web request can't fan out into a huge (slow/costly) job.
MAX_PAGES_LIMIT = 5


def _int_arg(name: str, default: int, *, low: int, high: int) -> int:
    """Read an int query param, clamped to a safe range."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(high, value))


def _run_search() -> tuple[list, dict]:
    """Execute a search from the current request args. Returns (products, params)."""
    params = {
        "search": (request.args.get("search") or request.args.get("q") or "").strip(),
        "category": (request.args.get("category") or "").strip(),
        "domain": (request.args.get("domain") or "amazon.com").strip(),
        "min_sales": _int_arg("min_sales", 50, low=0, high=10_000_000),
        "min_offers": _int_arg("min_offers", 6, low=0, high=1000),
        "max_pages": _int_arg("max_pages", 1, low=1, high=MAX_PAGES_LIMIT),
        "check_offers": request.args.get("check_offers", "1") not in ("0", "false", "off"),
    }
    api_key = os.environ.get("RAINFOREST_API_KEY", "")
    client = RainforestClient(api_key, amazon_domain=params["domain"])
    products = find_products(
        client,
        search_term=params["search"] or None,
        category_id=params["category"] or None,
        criteria=Criteria(
            min_sales=params["min_sales"],
            min_offers=params["min_offers"],
            check_offers=params["check_offers"],
        ),
        max_pages=params["max_pages"],
    )
    return products, params


@app.get("/healthz")
def healthz() -> Response:
    return jsonify(
        status="ok",
        api_key_configured=bool(os.environ.get("RAINFOREST_API_KEY")),
    )


@app.get("/api/search")
def api_search():
    if not (request.args.get("search") or request.args.get("q") or request.args.get("category")):
        return jsonify(error="Provide a 'search' (or 'q') term and/or a 'category' id."), 400
    try:
        products, params = _run_search()
    except RainforestError as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(
        criteria=params,
        count=len(products),
        results=[p.as_row() for p in products],
    )


@app.get("/")
def index() -> Response:
    has_query = bool(
        request.args.get("search") or request.args.get("q") or request.args.get("category")
    )
    error = None
    products: list = []
    params = {
        "search": request.args.get("search", ""),
        "category": request.args.get("category", ""),
        "domain": request.args.get("domain", "amazon.com"),
        "min_sales": request.args.get("min_sales", "50"),
        "min_offers": request.args.get("min_offers", "6"),
        "max_pages": request.args.get("max_pages", "1"),
        "check_offers": request.args.get("check_offers", "1") not in ("0", "false", "off"),
    }
    if has_query:
        try:
            products, ran = _run_search()
            params.update({k: str(v) for k, v in ran.items()})
            params["check_offers"] = ran["check_offers"]
        except RainforestError as exc:
            error = str(exc)
    return Response(_render_page(params, products, error, has_query), mimetype="text/html")


def _render_page(params: dict, products: list, error: str | None, has_query: bool) -> str:
    def esc(v) -> str:
        return (
            str(v)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        )

    rows = ""
    for p in products:
        sales = f"{p.recent_sales}+" if p.recent_sales is not None else "?"
        offers = p.offers_count if p.offers_count is not None else "?"
        price = f"{esc(p.currency)}{esc(p.price)}" if p.price is not None else "—"
        rows += (
            "<tr>"
            f"<td class='mono'><a href='{esc(p.link)}' target='_blank' rel='noopener'>{esc(p.asin)}</a></td>"
            f"<td class='num'>{sales}</td>"
            f"<td class='num'>{offers}</td>"
            f"<td class='num'>{price}</td>"
            f"<td>{esc(p.title)}</td>"
            "</tr>"
        )

    if has_query and not error and not products:
        results_block = "<p class='empty'>No products matched the criteria.</p>"
    elif products:
        results_block = (
            f"<p class='count'>{len(products)} matching product(s)</p>"
            "<table><thead><tr>"
            "<th>ASIN</th><th>Sales/mo</th><th>Offers</th><th>Price</th><th>Title</th>"
            "</tr></thead><tbody>" + rows + "</tbody></table>"
        )
    else:
        results_block = ""

    error_block = f"<p class='error'>⚠️ {esc(error)}</p>" if error else ""
    checked = "checked" if params.get("check_offers", True) else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Amazon Product Finder</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         margin: 0; padding: 2rem 1rem; background: #0f1115; color: #e8e8ea; }}
  .wrap {{ max-width: 1000px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .25rem; }}
  .sub {{ color: #9aa0a6; margin: 0 0 1.5rem; font-size: .9rem; }}
  form {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: .75rem; background: #171a21; padding: 1.25rem; border-radius: 12px;
          border: 1px solid #262b36; }}
  label {{ display: flex; flex-direction: column; gap: .3rem; font-size: .8rem; color: #9aa0a6; }}
  input, select {{ padding: .55rem .6rem; border-radius: 8px; border: 1px solid #2c323d;
          background: #0f1115; color: #e8e8ea; font-size: .9rem; }}
  .row-check {{ flex-direction: row; align-items: center; gap: .5rem; color: #e8e8ea; }}
  .actions {{ grid-column: 1 / -1; display: flex; gap: .75rem; align-items: center; }}
  button {{ background: #ff9900; color: #111; border: 0; padding: .6rem 1.4rem;
          border-radius: 8px; font-weight: 600; cursor: pointer; font-size: .95rem; }}
  button:hover {{ background: #ffad33; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 1.25rem; font-size: .88rem; }}
  th, td {{ text-align: left; padding: .55rem .6rem; border-bottom: 1px solid #262b36; }}
  th {{ color: #9aa0a6; font-weight: 600; }}
  td.num {{ text-align: right; white-space: nowrap; }}
  .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  a {{ color: #ff9900; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .count {{ color: #9aa0a6; margin-top: 1.25rem; }}
  .empty {{ color: #9aa0a6; margin-top: 1.25rem; }}
  .error {{ background: #3a1d1d; border: 1px solid #5a2a2a; color: #ffb4b4;
            padding: .75rem 1rem; border-radius: 8px; margin-top: 1.25rem; }}
  .hint {{ color: #6b7280; font-size: .75rem; margin-top: 1.5rem; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Amazon Product Finder</h1>
  <p class="sub">Surface products with strong recent monthly sales and multiple sellers.</p>
  <form method="get" action="/">
    <label>Search keyword
      <input name="search" value="{esc(params['search'])}" placeholder="wireless earbuds">
    </label>
    <label>Category id (optional)
      <input name="category" value="{esc(params['category'])}" placeholder="e.g. 172282">
    </label>
    <label>Amazon domain
      <input name="domain" value="{esc(params['domain'])}">
    </label>
    <label>Min sales / month
      <input name="min_sales" type="number" min="0" value="{esc(params['min_sales'])}">
    </label>
    <label>Min offers (sellers)
      <input name="min_offers" type="number" min="0" value="{esc(params['min_offers'])}">
    </label>
    <label>Pages to scan (max {MAX_PAGES_LIMIT})
      <input name="max_pages" type="number" min="1" max="{MAX_PAGES_LIMIT}" value="{esc(params['max_pages'])}">
    </label>
    <label class="row-check"><input type="checkbox" name="check_offers" value="1" {checked}> Check seller count</label>
    <div class="actions"><button type="submit">Find products</button></div>
  </form>
  {error_block}
  {results_block}
  <p class="hint">JSON API: <span class="mono">/api/search?search=earbuds&amp;min_sales=50&amp;min_offers=6</span></p>
</div>
</body>
</html>"""


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
