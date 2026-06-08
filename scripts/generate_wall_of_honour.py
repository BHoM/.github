"""Generate BHoM Wall of Honour and splice into profile/README.md."""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import requests

from scripts.github_api import GITHUB_API, get_one, make_session, paginated_get


def list_org_repos(session: requests.Session, org: str) -> list[dict[str, Any]]:
    """List non-archived repos in `org`, excluding the org's `.github` repo."""
    url = f"{GITHUB_API}/orgs/{org}/repos"
    all_repos = paginated_get(session, url, params={"per_page": 100, "type": "all"})
    return [r for r in all_repos if not r["archived"] and r["name"] != ".github"]


def fetch_repo_contributors(session: requests.Session, org: str, repo: str) -> list[dict[str, Any]]:
    """Fetch contributors for a single repo. Returns [] for an empty repo (HTTP 204)."""
    url = f"{GITHUB_API}/repos/{org}/{repo}/contributors"
    return paginated_get(session, url, params={"per_page": 100, "anon": "false"})
