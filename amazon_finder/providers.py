"""Pluggable data-provider layer.

Both the CLI and the web service talk to a provider through one method,
``find(...)``, so swapping backends (RapidAPI, Rainforest, ...) is a config
choice rather than a code change.
"""

from __future__ import annotations

from .errors import ProviderError
from .finder import Criteria, find_products as _rainforest_find
from .rainforest import RainforestClient
from .rapidapi import RapidApiClient, find_products_rapidapi

DEFAULT_PROVIDER = "rapidapi"
PROVIDERS = ("rapidapi", "rainforest")

# Environment variable that holds each provider's API key.
PROVIDER_ENV = {
    "rapidapi": "RAPIDAPI_KEY",
    "rainforest": "RAINFOREST_API_KEY",
}

# Human-friendly names for help text / UI.
PROVIDER_LABELS = {
    "rapidapi": "RapidAPI (Real-Time Amazon Data)",
    "rainforest": "Rainforest API",
}


class _Provider:
    name = ""

    def find(self, **kwargs):  # pragma: no cover - interface
        raise NotImplementedError


class RainforestProvider(_Provider):
    name = "rainforest"

    def __init__(self, api_key: str, domain: str):
        self.client = RainforestClient(api_key, amazon_domain=domain)

    def find(self, *, search_term, category_id, criteria, max_pages, sort_by, on_progress):
        return _rainforest_find(
            self.client,
            search_term=search_term,
            category_id=category_id,
            criteria=criteria,
            max_pages=max_pages,
            sort_by=sort_by,
            on_progress=on_progress,
        )


class RapidApiProvider(_Provider):
    name = "rapidapi"

    def __init__(self, api_key: str, domain: str):
        self.client = RapidApiClient(api_key, amazon_domain=domain)

    def find(self, *, search_term, category_id, criteria, max_pages, sort_by, on_progress):
        return find_products_rapidapi(
            self.client,
            search_term=search_term,
            category_id=category_id,
            criteria=criteria,
            max_pages=max_pages,
            sort_by=sort_by,
            on_progress=on_progress,
        )


_BUILDERS = {
    "rainforest": RainforestProvider,
    "rapidapi": RapidApiProvider,
}


def build_provider(name: str | None, *, api_key: str, domain: str) -> _Provider:
    name = (name or DEFAULT_PROVIDER).lower()
    builder = _BUILDERS.get(name)
    if builder is None:
        raise ProviderError(
            f"Unknown provider {name!r}. Choose from: {', '.join(PROVIDERS)}."
        )
    return builder(api_key, domain)
