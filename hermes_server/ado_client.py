"""Backward-compatibility module alias for azdo_client."""

# Local
from .azdo_client import (
    API_VERSION,
    _auth_headers,
    _avatar_cache,
    _group_cache,
    _identity_cache,
    get_pr_reviewers,
    get_thread_participants,
    get_user_avatar_b64,
    get_user_groups,
    resolve_identity,
    settings,
)

__all__ = [
    "API_VERSION",
    "_auth_headers",
    "_avatar_cache",
    "_group_cache",
    "_identity_cache",
    "get_pr_reviewers",
    "get_thread_participants",
    "get_user_avatar_b64",
    "get_user_groups",
    "resolve_identity",
    "settings",
]

