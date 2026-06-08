# scripts/github_api.py
"""Thin GitHub REST API helpers: session with retry, paginated GET."""
from __future__ import annotations

import re
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

GITHUB_API = "https://api.github.com"
_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def make_session(token: str) -> requests.Session:
    """Build a requests Session with retry policy and auth header."""
    session = requests.Session()
    session.headers.update({
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _parse_next(link_header: str | None) -> str | None:
    """Return next-page URL from a Link header, or None."""
    if not link_header:
        return None
    match = _LINK_NEXT_RE.search(link_header)
    return match.group(1) if match else None


def paginated_get(session: requests.Session, url: str, params: dict | None = None) -> list[Any]:
    """GET a paginated GitHub endpoint, following Link rel=next, returning the flat list."""
    items: list[Any] = []
    next_url: str | None = url
    next_params = params
    while next_url:
        response = session.get(next_url, params=next_params, timeout=30)
        response.raise_for_status()
        page = response.json()
        if isinstance(page, list):
            items.extend(page)
        else:
            items.append(page)
        next_url = _parse_next(response.headers.get("Link"))
        next_params = None
    return items


def get_one(session: requests.Session, url: str) -> dict[str, Any]:
    """Single-object GET (no pagination). Returns parsed JSON dict."""
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.json()
