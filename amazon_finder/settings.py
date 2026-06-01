"""Runtime-editable settings (access code + API keys), stored in SQLite.

Resolution order for any setting is **UI value (DB) first, then the environment
variable** from the Render Blueprint. This lets the Blueprint seed an initial
value while the in-app Settings page can override it later.

The access code is stored only as a salted hash (never shown back). API keys
are stored as-is because they must be replayed to the provider; the UI only
ever displays a masked version.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3

from .history import _db_path

_CODE_SALT = "amzfinder$v1$"

_KEY_ENV = {"rapidapi": "RAPIDAPI_KEY", "rainforest": "RAINFOREST_API_KEY"}
_KEY_SETTING = {"rapidapi": "rapidapi_key", "rainforest": "rainforest_key"}


def _connect() -> sqlite3.Connection:
    path = _db_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_settings() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )


def get_setting(key: str, default: str | None = None) -> str | None:
    init_settings()
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    init_settings()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def delete_setting(key: str) -> None:
    init_settings()
    with _connect() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


# --- access code ------------------------------------------------------------
def _hash_code(code: str) -> str:
    return hashlib.sha256((_CODE_SALT + code).encode("utf-8")).hexdigest()


def set_access_code(code: str) -> None:
    set_setting("access_code_hash", _hash_code(code))


def access_code_source() -> str:
    if get_setting("access_code_hash"):
        return "ui"
    if os.environ.get("ACCESS_CODE"):
        return "blueprint"
    return "none"


def has_access_code() -> bool:
    return access_code_source() != "none"


def verify_access_code(code: str) -> bool:
    stored = get_setting("access_code_hash")
    if stored:
        return hmac.compare_digest(stored, _hash_code(code))
    env_code = os.environ.get("ACCESS_CODE", "")
    if env_code:
        return hmac.compare_digest(code, env_code)
    return False


# --- API keys ---------------------------------------------------------------
def get_api_key(provider: str) -> str:
    setting_name = _KEY_SETTING.get(provider, "")
    stored = get_setting(setting_name) if setting_name else None
    if stored:
        return stored
    return os.environ.get(_KEY_ENV.get(provider, ""), "")


def set_api_key(provider: str, key: str) -> None:
    setting_name = _KEY_SETTING.get(provider)
    if not setting_name:
        return
    if key:
        set_setting(setting_name, key)
    else:
        delete_setting(setting_name)


def api_key_source(provider: str) -> str:
    if get_setting(_KEY_SETTING.get(provider, "")):
        return "ui"
    if os.environ.get(_KEY_ENV.get(provider, "")):
        return "blueprint"
    return "none"


def mask(secret: str | None) -> str:
    if not secret:
        return "—"
    return "••••" + secret[-4:] if len(secret) > 4 else "••••"
