"""Persistent search history, stored in a local SQLite database.

Each search (its criteria and full result set) is saved so past runs can be
revisited from the web dashboard without spending another API call.

The database path comes from ``HISTORY_DB`` (default ``data/history.db``). On
Render's free tier the filesystem is ephemeral, so attach a persistent disk and
point ``HISTORY_DB`` at it to keep history across restarts.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta

DEFAULT_DB = "data/history.db"

# Don't record the same search twice within this window (stops page refreshes
# and double-submits from flooding the history list).
_DEDUP_WINDOW = timedelta(minutes=2)

_PARAM_KEYS = (
    "provider", "search", "category", "domain",
    "min_sales", "min_offers", "max_pages",
)


def _db_path() -> str:
    return os.environ.get("HISTORY_DB", DEFAULT_DB)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS searches (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at    TEXT    NOT NULL,
                provider      TEXT,
                search        TEXT,
                category      TEXT,
                domain        TEXT,
                min_sales     INTEGER,
                min_offers    INTEGER,
                max_pages     INTEGER,
                check_offers  INTEGER,
                result_count  INTEGER,
                results_json  TEXT    NOT NULL
            )
            """
        )


def _same_params(row: sqlite3.Row, params: dict) -> bool:
    for key in _PARAM_KEYS:
        if str(row[key] if row[key] is not None else "") != str(params.get(key, "") or ""):
            return False
    return True


def add_search(params: dict, products) -> int:
    """Persist a search and its results; return the row id.

    If an identical search was recorded within the dedup window, the existing
    row id is returned instead of inserting a duplicate.
    """
    init_db()
    results = [p.as_row() for p in products]
    now = datetime.now(timezone.utc)

    with _connect() as conn:
        latest = conn.execute(
            "SELECT * FROM searches ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if latest is not None and _same_params(latest, params):
            try:
                prev = datetime.fromisoformat(latest["created_at"])
                if now - prev < _DEDUP_WINDOW:
                    return latest["id"]
            except ValueError:
                pass

        cur = conn.execute(
            """
            INSERT INTO searches (
                created_at, provider, search, category, domain,
                min_sales, min_offers, max_pages, check_offers,
                result_count, results_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.isoformat(timespec="seconds"),
                params.get("provider", ""),
                params.get("search", ""),
                params.get("category", ""),
                params.get("domain", ""),
                int(params.get("min_sales", 0) or 0),
                int(params.get("min_offers", 0) or 0),
                int(params.get("max_pages", 0) or 0),
                1 if params.get("check_offers") else 0,
                len(results),
                json.dumps(results),
            ),
        )
        return int(cur.lastrowid)


def list_searches(limit: int = 100) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, provider, search, category, domain,
                   min_sales, min_offers, max_pages, check_offers, result_count
            FROM searches ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_search(search_id: int) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM searches WHERE id = ?", (search_id,)
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["results"] = json.loads(data.pop("results_json"))
    return data
