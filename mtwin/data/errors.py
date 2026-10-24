"""Exception hierarchy for the data layer."""

from __future__ import annotations


class DataError(Exception):
    """Base class for every recoverable data-layer failure."""


class ProviderError(DataError):
    """A provider could not deliver usable data (network, HTTP status or bad payload)."""
