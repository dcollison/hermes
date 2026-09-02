"""Backward-compatibility module alias for azdo."""

# Local
from .azdo import API_VERSION, _auth_headers, resolve_callback_url, resolve_identity

__all__ = [
    "API_VERSION",
    "_auth_headers",
    "resolve_callback_url",
    "resolve_identity",
]

