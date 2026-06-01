"""Shared exception types across data providers."""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Base class for any data-provider (API) failure.

    CLI and web layers catch this so they don't need to know which backend
    (Rainforest, Keepa, ...) produced the error.
    """
