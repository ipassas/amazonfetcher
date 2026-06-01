"""Flask web dashboard for the Amazon product finder.

Features:
  * Pastel, card-based UI.
  * Persistent, revisitable search history (SQLite).
  * Optional passcode gate (set via Blueprint env or the Settings page).
  * Settings page to change the passcode and provider API key from the UI.

Routes:
  GET  /                 search form + results
  GET  /api/search       JSON API
  GET  /history          past searches
  GET  /history/<id>     a saved result set
  GET  /settings         change passcode / API key
  POST /settings         save settings
  GET/POST /login        passcode gate
  GET  /logout           clear session
  GET  /healthz          health check (always open)

Run locally:  python -m amazon_finder.web
On Render:    gunicorn amazon_finder.web:app --bind 0.0.0.0:$PORT
"""

from __future__ import annotations

import os
import secrets

from flask import Flask, request, jsonify, Response, session, redirect, url_for

from . import history, settings as settings_store
from .errors import ProviderError
from .finder import Criteria
from .providers import DEFAULT_PROVIDER, build_provider

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

MAX_PAGES_LIMIT = 5

# Pastel palette cycled across result/history cards for the playful look.
PALETTE = ["#FFE27A", "#F8B9D4", "#B7D39B", "#C9C6F0", "#FAD2AE", "#A7DDE0"]

_OPEN_ENDPOINTS = {"login", "healthz", "static"}


# --------------------------------------------------------------------------- #
# Auth gate
# --------------------------------------------------------------------------- #
@app.before_request
def _gate():
    if not settings_store.has_access_code():
        return None
    if request.endpoint in _OPEN_ENDPOINTS:
        return None
    if not session.get("authed"):
        return redirect(url_for("login", next=request.path))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if not settings_store.has_access_code():
        return redirect(url_for("index"))
    nxt = request.values.get("next") or url_for("index")
    if not nxt.startswith("/"):
        nxt = url_for("index")
    if request.method == "POST":
        if settings_store.verify_access_code(request.form.get("code", "")):
            session["authed"] = True
            return redirect(nxt)
        return Response(_login_page(nxt, error="Incorrect code."), mimetype="text/html"), 401
    return Response(_login_page(nxt, error=None), mimetype="text/html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------- #
# Search helpers
# --------------------------------------------------------------------------- #
def _provider_name() -> str:
    return (request.args.get("provider") or os.environ.get("PROVIDER") or DEFAULT_PROVIDER).lower()


def _int_arg(name: str, default: int, *, low: int, high: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(high, value))


def _run_search() -> tuple[list[dict], dict]:
    """Run a search from request args; persist it; return (result rows, params)."""
    params = {
        "search": (request.args.get("search") or request.args.get("q") or "").strip(),
        "category": (request.args.get("category") or "").strip(),
        "domain": (request.args.get("domain") or "amazon.com").strip(),
        "min_sales": _int_arg("min_sales", 50, low=0, high=10_000_000),
        "min_offers": _int_arg("min_offers", 6, low=0, high=1000),
        "max_pages": _int_arg("max_pages", 1, low=1, high=MAX_PAGES_LIMIT),
        "check_offers": request.args.get("check_offers", "1") not in ("0", "false", "off"),
        "provider": _provider_name(),
    }
    api_key = settings_store.get_api_key(params["provider"])
    provider = build_provider(params["provider"], api_key=api_key, domain=params["domain"])
    products = provider.find(
        search_term=params["search"] or None,
        category_id=params["category"] or None,
        criteria=Criteria(
            min_sales=params["min_sales"],
            min_offers=params["min_offers"],
            check_offers=params["check_offers"],
        ),
        max_pages=params["max_pages"],
        sort_by=None,
        on_progress=None,
    )
    try:
        history.add_search(params, products)
    except Exception:  # history must never break a search
        pass
    return [p.as_row() for p in products], params


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/healthz")
def healthz() -> Response:
    provider = (os.environ.get("PROVIDER") or DEFAULT_PROVIDER).lower()
    return jsonify(
        status="ok",
        provider=provider,
        api_key_configured=bool(settings_store.get_api_key(provider)),
        passcode_enabled=settings_store.has_access_code(),
    )


@app.get("/api/search")
def api_search():
    if not (request.args.get("search") or request.args.get("q") or request.args.get("category")):
        return jsonify(error="Provide a 'search' (or 'q') term and/or a 'category' id."), 400
    try:
        rows, params = _run_search()
    except ProviderError as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(criteria=params, count=len(rows), results=rows)


@app.get("/")
def index() -> Response:
    has_query = bool(
        request.args.get("search") or request.args.get("q") or request.args.get("category")
    )
    form = {
        "search": request.args.get("search", ""),
        "category": request.args.get("category", ""),
        "domain": request.args.get("domain", "amazon.com"),
        "min_sales": request.args.get("min_sales", "50"),
        "min_offers": request.args.get("min_offers", "6"),
        "max_pages": request.args.get("max_pages", "1"),
        "check_offers": request.args.get("check_offers", "1") not in ("0", "false", "off"),
        "provider": _provider_name(),
    }
    rows: list[dict] = []
    error = None
    if has_query:
        try:
            rows, _ = _run_search()
        except ProviderError as exc:
            error = str(exc)

    body = _hero() + _search_form(form)
    if error:
        body += f"<div class='banner error'>⚠️ {esc(error)}</div>"
    if has_query and not error:
        body += _results_section(rows, form["search"] or form["category"])
    return Response(_shell("Product Finder", body, active="search"), mimetype="text/html")


@app.get("/history")
def history_list() -> Response:
    rows = history.list_searches()
    return Response(_shell("History", _history_page(rows), active="history"),
                    mimetype="text/html")


@app.get("/history/<int:search_id>")
def history_detail(search_id: int) -> Response:
    record = history.get_search(search_id)
    if record is None:
        body = "<div class='banner empty'>That saved search no longer exists.</div>"
        return Response(_shell("History", body, active="history"), mimetype="text/html"), 404
    body = _saved_search_header(record) + _results_section(
        record["results"], record.get("search") or record.get("category") or "search"
    )
    return Response(_shell("History", body, active="history"), mimetype="text/html")


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    message = None
    error = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "code":
            code = request.form.get("code", "")
            confirm = request.form.get("confirm", "")
            if len(code) < 4:
                error = "Passcode must be at least 4 characters."
            elif code != confirm:
                error = "Passcode and confirmation don't match."
            else:
                settings_store.set_access_code(code)
                session["authed"] = True  # keep current session valid
                message = "Passcode updated."
        elif action == "key":
            provider = request.form.get("provider", DEFAULT_PROVIDER)
            settings_store.set_api_key(provider, request.form.get("api_key", "").strip())
            message = "API key saved."
        else:
            error = "Unknown action."
    return Response(_shell("Settings", _settings_page(message, error), active="settings"),
                    mimetype="text/html")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def esc(value) -> str:
    return (
        str(value)
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _nav(active: str) -> str:
    def link(href, label, key):
        cls = " class='active'" if key == active else ""
        return f"<a{cls} href='{href}'>{label}</a>"

    links = (
        link(url_for("index"), "Search", "search")
        + link(url_for("history_list"), "History", "history")
        + link(url_for("settings_page"), "Settings", "settings")
    )
    if settings_store.has_access_code() and session.get("authed"):
        links += f"<a href='{url_for('logout')}'>Logout</a>"
    return (
        "<nav class='topbar'><div class='brand' data-tip='Never Get Married' title='Never Get Married'>"
        "<span class='dot'></span>HaiderHunt</div>"
        f"<div class='navlinks'>{links}</div></nav>"
    )


def _shell(title: str, inner: str, *, active: str = "search", nav: bool = True) -> str:
    nav_html = _nav(active) if nav else ""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(title)}</title>"
        + _FONT_LINK + "<style>" + _STYLES + "</style></head><body>"
        + nav_html + "<main class='wrap'>" + inner + "</main></body></html>"
    )


def _hero() -> str:
    return (
        "<section class='hero'><span class='blob b1'></span><span class='blob b2'></span>"
        "<h1>Discover<br>winning products</h1>"
        "<p>Surface Amazon products with strong monthly sales and plenty of sellers.</p>"
        "</section>"
    )


def _search_form(f: dict) -> str:
    checked = "checked" if f.get("check_offers", True) else ""
    return (
        "<section class='card search-card'><form class='grid' method='get' action='/'>"
        f"<label>Keyword<input name='search' value='{esc(f['search'])}' placeholder='wireless earbuds'></label>"
        f"<label>Category id<input name='category' value='{esc(f['category'])}' placeholder='optional'></label>"
        f"<label>Domain<input name='domain' value='{esc(f['domain'])}'></label>"
        f"<label>Min sales / mo<input name='min_sales' type='number' min='0' value='{esc(f['min_sales'])}'></label>"
        f"<label>Min sellers<input name='min_offers' type='number' min='0' value='{esc(f['min_offers'])}'></label>"
        f"<label>Pages (max {MAX_PAGES_LIMIT})<input name='max_pages' type='number' min='1' max='{MAX_PAGES_LIMIT}' value='{esc(f['max_pages'])}'></label>"
        f"<label class='check'><input type='checkbox' name='check_offers' value='1' {checked}> Check seller count</label>"
        "<div class='actions'><button class='primary' type='submit'>Find products →</button>"
        f"<span class='muted'>via {esc(f.get('provider',''))}</span></div>"
        "</form></section>"
    )


def _pill(text: str, *, dark: bool = False) -> str:
    cls = "pill dark" if dark else "pill"
    return f"<span class='{cls}'>{esc(text)}</span>"


def _product_card(p: dict, color: str) -> str:
    sales = p.get("recent_sales")
    sales_text = f"🔥 {sales}+/mo" if sales is not None else "🔥 sales n/a"
    offers = p.get("offers_count")
    offers_text = f"🏷 {offers} sellers" if offers is not None else "🏷 sellers n/a"
    price = p.get("price")
    pills = _pill(sales_text, dark=True) + _pill(offers_text)
    if price is not None:
        pills += _pill(f"{p.get('currency','')}{price}")
    link = p.get("link") or ""
    view = (
        f"<a class='view' href='{esc(link)}' target='_blank' rel='noopener'>View on Amazon →</a>"
        if link else ""
    )
    return (
        f"<div class='pcard' style='background:{color}'>"
        f"<div class='title'>{esc(p.get('title','') or p.get('asin',''))}</div>"
        f"<div class='pills'>{pills}</div>{view}</div>"
    )


def _results_section(rows: list[dict], query: str) -> str:
    if not rows:
        return "<div class='banner empty'>No products matched the criteria.</div>"
    head = (
        "<div class='sectionhead'><h2>Results</h2>"
        f"<span class='muted'>{len(rows)} product(s) for “{esc(query)}”</span></div>"
    )
    cards = "".join(
        _product_card(p, PALETTE[i % len(PALETTE)]) for i, p in enumerate(rows)
    )
    return head + f"<div class='cards'>{cards}</div>"


def _saved_search_header(rec: dict) -> str:
    when = (rec.get("created_at") or "").replace("T", " ")
    crit = (
        f"≥{rec.get('min_sales')} sales · ≥{rec.get('min_offers')} sellers · "
        f"{esc(rec.get('domain',''))} · {esc(rec.get('provider',''))}"
    )
    label = rec.get("search") or (f"category {rec.get('category')}" if rec.get("category") else "—")
    return (
        "<section class='hero' style='background:#C9C6F0'>"
        f"<h1>{esc(label)}</h1>"
        f"<p>{esc(crit)}<br><span class='muted'>saved {esc(when)} UTC</span></p>"
        f"<a class='backlink' href='{url_for('history_list')}'>← back to history</a>"
        "</section>"
    )


def _history_page(rows: list[dict]) -> str:
    head = "<div class='sectionhead'><h2>Search history</h2><span class='muted'>most recent first</span></div>"
    if not rows:
        return head + "<div class='banner empty'>No searches yet. Run one from the Search tab.</div>"
    items = ""
    for i, r in enumerate(rows):
        color = PALETTE[i % len(PALETTE)]
        label = r.get("search") or (f"category {r.get('category')}" if r.get("category") else "—")
        when = (r.get("created_at") or "").replace("T", " ")
        meta = (
            f"≥{r.get('min_sales')} sales · ≥{r.get('min_offers')} sellers · "
            f"{esc(r.get('domain',''))} · {esc(r.get('provider',''))} · {esc(when)} UTC"
        )
        items += (
            f"<a class='hrow' style='background:{color}' href='{url_for('history_detail', search_id=r['id'])}'>"
            f"<div><div class='q'>{esc(label)}</div><div class='meta'>{meta}</div></div>"
            f"<div class='count'>{r.get('result_count', 0)}</div></a>"
        )
    return head + f"<div class='hlist'>{items}</div>"


def _settings_page(message: str | None, error: str | None) -> str:
    code_src = settings_store.access_code_source()
    code_status = {
        "ui": "Set via this page.",
        "blueprint": "Set via Blueprint (ACCESS_CODE). You can override it here.",
        "none": "No passcode — the dashboard is currently open.",
    }[code_src]

    provider = (os.environ.get("PROVIDER") or DEFAULT_PROVIDER).lower()
    key_src = settings_store.api_key_source(provider)
    key_status = {
        "ui": "Set via this page.",
        "blueprint": "Set via Blueprint env var. You can override it here.",
        "none": "Not configured — searches will fail until you add a key.",
    }[key_src]
    masked = settings_store.mask(settings_store.get_api_key(provider))

    banner = ""
    if message:
        banner = f"<div class='banner info'>✅ {esc(message)}</div>"
    if error:
        banner = f"<div class='banner error'>⚠️ {esc(error)}</div>"

    return (
        "<div class='sectionhead'><h2>Settings</h2></div>" + banner
        + "<section class='card'><h3>Passcode</h3>"
        f"<p class='muted'>{esc(code_status)}</p>"
        "<form class='stack' method='post' action='/settings'>"
        "<input type='hidden' name='action' value='code'>"
        "<label>New passcode<input name='code' type='password' autocomplete='new-password' placeholder='at least 4 characters'></label>"
        "<label>Confirm passcode<input name='confirm' type='password' autocomplete='new-password'></label>"
        "<div class='actions'><button class='primary' type='submit'>Update passcode</button></div>"
        "</form></section>"
        f"<section class='card' style='margin-top:1rem'><h3>{esc(provider)} API key</h3>"
        f"<p class='muted'>{esc(key_status)} Current: <span class='mono'>{esc(masked)}</span></p>"
        "<form class='stack' method='post' action='/settings'>"
        "<input type='hidden' name='action' value='key'>"
        f"<input type='hidden' name='provider' value='{esc(provider)}'>"
        "<label>New API key<input name='api_key' autocomplete='off' placeholder='paste key (leave blank to clear)'></label>"
        "<div class='actions'><button class='primary' type='submit'>Save API key</button></div>"
        "</form></section>"
    )


def _login_page(nxt: str, error: str | None) -> str:
    err = f"<div class='banner error'>⚠️ {esc(error)}</div>" if error else ""
    body = (
        "<div class='login-wrap'><section class='card login-card'>"
        "<div class='brand' data-tip='Never Get Married' title='Never Get Married' style='justify-content:center'><span class='dot'></span>HaiderHunt</div>"
        "<h1>Enter passcode</h1><p class='muted'>This dashboard is protected.</p>"
        + err
        + f"<form method='post' action='/login'><input type='hidden' name='next' value='{esc(nxt)}'>"
        "<input name='code' type='password' autocomplete='current-password' placeholder='passcode' autofocus>"
        "<button class='primary' type='submit'>Unlock</button></form></section></div>"
    )
    return _shell("Login", body, nav=False)


# --------------------------------------------------------------------------- #
# Static assets (fonts + styles)
# --------------------------------------------------------------------------- #
_FONT_LINK = (
    "<link rel='preconnect' href='https://fonts.googleapis.com'>"
    "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
    "<link href='https://fonts.googleapis.com/css2?"
    "family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&"
    "family=Inter:wght@400;500;600;700&display=swap' rel='stylesheet'>"
)

_STYLES = """
:root{--bg:#FBF6EC;--ink:#16131f;--muted:#807c8c;--card:#fff;--line:#ece7da;
--shadow:0 12px 32px rgba(20,16,30,.07);--yellow:#FFE27A;--pink:#F8B9D4;--mint:#A7DDE0;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;}
h1,h2,h3{font-family:'Bricolage Grotesque','Inter',system-ui,sans-serif;
letter-spacing:-.02em;margin:0;line-height:1.05;}
a{color:inherit;}
.wrap{max-width:1080px;margin:0 auto;padding:.5rem 1.25rem 4rem;}
nav.topbar{position:sticky;top:0;z-index:10;display:flex;align-items:center;
justify-content:space-between;max-width:1080px;margin:0 auto;padding:1rem 1.25rem;
backdrop-filter:saturate(120%) blur(6px);}
.brand{display:flex;align-items:center;gap:.5rem;font-family:'Bricolage Grotesque';
font-weight:800;font-size:1.15rem;position:relative;cursor:default;}
.brand .dot{width:13px;height:13px;border-radius:50%;background:var(--ink);}
.brand[data-tip]::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 8px);
background:var(--ink);color:#fff;font-family:'Inter',sans-serif;font-weight:600;font-size:.78rem;
padding:.45rem .75rem;border-radius:12px;white-space:nowrap;opacity:0;transform:translateY(-4px);
pointer-events:none;transition:opacity .15s ease,transform .15s ease;box-shadow:var(--shadow);z-index:20;}
.brand[data-tip]:hover::after{opacity:1;transform:translateY(0);}
.navlinks{display:flex;gap:.4rem;flex-wrap:wrap;}
.navlinks a{text-decoration:none;font-weight:600;font-size:.88rem;padding:.5rem .9rem;
border-radius:999px;background:#fff;border:1px solid var(--line);}
.navlinks a:hover{background:var(--yellow);border-color:var(--yellow);}
.navlinks a.active{background:var(--ink);color:#fff;border-color:var(--ink);}
.hero{background:var(--yellow);border-radius:30px;padding:2.2rem;position:relative;
overflow:hidden;box-shadow:var(--shadow);}
.hero h1{font-size:clamp(2.1rem,5.5vw,3.4rem);font-weight:800;}
.hero p{margin:.7rem 0 0;font-weight:500;color:#3a3540;max-width:34ch;}
.hero .blob{position:absolute;border-radius:50%;}
.hero .b1{width:130px;height:130px;background:var(--pink);right:-26px;top:-26px;}
.hero .b2{width:84px;height:84px;background:#B7D39B;right:96px;bottom:-34px;
border-radius:42% 58% 55% 45%;}
.hero .backlink{display:inline-block;margin-top:1rem;font-weight:700;text-decoration:none;
background:#fff;padding:.45rem .9rem;border-radius:999px;font-size:.85rem;}
.card{background:var(--card);border:1px solid var(--line);border-radius:26px;
padding:1.4rem;box-shadow:var(--shadow);}
.search-card{margin-top:1.25rem;}
form.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:.9rem;}
form.stack{display:flex;flex-direction:column;gap:.9rem;max-width:420px;margin-top:.6rem;}
label{display:flex;flex-direction:column;gap:.35rem;font-size:.74rem;font-weight:700;
color:var(--muted);text-transform:uppercase;letter-spacing:.05em;}
input,select{font-family:inherit;font-size:.95rem;padding:.7rem .8rem;border-radius:14px;
border:1.5px solid var(--line);background:#fff;color:var(--ink);width:100%;}
input:focus,select:focus{outline:none;border-color:var(--ink);}
.check{flex-direction:row;align-items:center;gap:.5rem;text-transform:none;
letter-spacing:0;color:var(--ink);font-size:.9rem;font-weight:600;}
.check input{width:auto;}
.actions{grid-column:1/-1;display:flex;gap:.85rem;align-items:center;flex-wrap:wrap;}
button.primary{font-family:'Bricolage Grotesque';font-weight:800;font-size:1rem;
background:var(--ink);color:#fff;border:0;padding:.8rem 1.7rem;border-radius:999px;
cursor:pointer;transition:transform .08s ease;}
button.primary:hover{transform:translateY(-1px);}
.muted{color:var(--muted);font-weight:500;}
.mono{font-family:ui-monospace,Menlo,monospace;}
.sectionhead{display:flex;align-items:baseline;justify-content:space-between;
gap:1rem;margin:2.2rem .3rem 1rem;flex-wrap:wrap;}
.sectionhead h2{font-size:1.6rem;font-weight:800;}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(235px,1fr));gap:1rem;}
.pcard{border-radius:24px;padding:1.15rem;box-shadow:var(--shadow);display:flex;
flex-direction:column;gap:.75rem;min-height:180px;}
.pcard .title{font-weight:600;font-size:.98rem;line-height:1.28;
display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
.pills{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:auto;}
.pill{font-size:.76rem;font-weight:700;padding:.34rem .62rem;border-radius:999px;
background:rgba(0,0,0,.09);white-space:nowrap;}
.pill.dark{background:var(--ink);color:#fff;}
.pcard a.view{align-self:flex-start;text-decoration:none;font-weight:700;font-size:.82rem;
background:#fff;padding:.42rem .85rem;border-radius:999px;border:1.5px solid rgba(0,0,0,.12);}
.pcard a.view:hover{background:var(--ink);color:#fff;}
.banner{border-radius:18px;padding:.95rem 1.15rem;font-weight:600;margin-top:1.25rem;}
.banner.error{background:#ffd9d9;color:#7a1f1f;}
.banner.empty{background:#fff;border:1.5px dashed var(--line);color:var(--muted);}
.banner.info{background:var(--mint);color:#11353d;}
.hlist{display:flex;flex-direction:column;gap:.8rem;}
.hrow{display:flex;align-items:center;justify-content:space-between;gap:1rem;
border-radius:20px;padding:1.1rem 1.2rem;text-decoration:none;box-shadow:var(--shadow);
transition:transform .08s ease;}
.hrow:hover{transform:translateY(-1px);}
.hrow .q{font-family:'Bricolage Grotesque';font-weight:800;font-size:1.08rem;}
.hrow .meta{font-size:.78rem;color:#3a3540;font-weight:500;margin-top:.2rem;}
.hrow .count{font-family:'Bricolage Grotesque';font-weight:800;font-size:1.5rem;}
.login-wrap{min-height:78vh;display:flex;align-items:center;justify-content:center;}
.login-card{width:100%;max-width:390px;text-align:center;}
.login-card h1{font-size:1.9rem;margin:.6rem 0 .2rem;}
.login-card form{margin-top:1.1rem;display:flex;flex-direction:column;gap:.8rem;}
.card h3{font-size:1.15rem;font-weight:800;}
@media(max-width:520px){.hero{padding:1.5rem;}.wrap{padding-bottom:3rem;}}
"""


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
