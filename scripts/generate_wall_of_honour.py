"""Generate BHoM Wall of Honour and splice into profile/README.md."""
from __future__ import annotations

import os
import re
import sys
import unicodedata
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


def filter_bots(contributors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove bot accounts (type=Bot or login ending in [bot])."""
    return [
        c for c in contributors
        if c.get("type") != "Bot" and not c["login"].endswith("[bot]")
    ]


def aggregate_contributors(
    per_repo_lists: list[list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """De-duplicate contributors by login, summing contributions across repos."""
    aggregated: dict[str, dict[str, Any]] = {}
    for contributors in per_repo_lists:
        for c in contributors:
            login = c["login"]
            existing = aggregated.get(login)
            if existing is None:
                aggregated[login] = {
                    "avatar_url": c["avatar_url"],
                    "contributions": c["contributions"],
                }
            else:
                existing["contributions"] += c["contributions"]
    return aggregated


def enrich_display_names(
    session: requests.Session,
    contributors: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Fetch each contributor's display name; fall back to login when blank."""
    for login, info in contributors.items():
        user = get_one(session, f"{GITHUB_API}/users/{login}")
        name = (user.get("name") or "").strip()
        info["name"] = name if name else login
    return contributors


GRID_COLS = 7
AVATAR_SIZE = 100


def render_wall(contributors: dict[str, dict[str, Any]], last_updated: str) -> str:
    """Render the markdown block (markers included) for the wall."""
    if not contributors:
        return (
            "<!-- WALL:START -->\n"
            "## Wall of Honour\n\n"
            "Wall coming soon — no contributors yet.\n\n"
            f"_Last updated: {last_updated}_\n"
            "<!-- WALL:END -->"
        )

    sorted_logins = sorted(
        contributors.keys(),
        key=lambda login: unicodedata.normalize("NFD", contributors[login]["name"].casefold()),
    )

    rows: list[str] = []
    for row_start in range(0, len(sorted_logins), GRID_COLS):
        row_logins = sorted_logins[row_start:row_start + GRID_COLS]
        cells = [_render_cell(login, contributors[login]) for login in row_logins]
        rows.append("  <tr>\n" + "\n".join(cells) + "\n  </tr>")

    return (
        "<!-- WALL:START -->\n"
        "## Wall of Honour\n\n"
        f"Thank you to the **{len(contributors)} people** who have contributed to BHoM.\n\n"
        "<table>\n"
        + "\n".join(rows)
        + "\n</table>\n\n"
        f"_Last updated: {last_updated}_\n"
        "<!-- WALL:END -->"
    )


def _render_cell(login: str, info: dict[str, Any]) -> str:
    name = info["name"]
    return (
        "    <td align=\"center\">\n"
        f"      <a href=\"https://github.com/{login}\">"
        f"<img src=\"https://github.com/{login}.png?size={AVATAR_SIZE}\" "
        f"width=\"{AVATAR_SIZE}\" height=\"{AVATAR_SIZE}\" /><br/>"
        f"<sub><b>{name}</b></sub></a>\n"
        "    </td>"
    )


WALL_MARKER_START = "<!-- WALL:START -->"
WALL_MARKER_END = "<!-- WALL:END -->"
_WALL_BLOCK_RE = re.compile(
    re.escape(WALL_MARKER_START) + r".*?" + re.escape(WALL_MARKER_END),
    re.DOTALL,
)

BOOTSTRAP_TEMPLATE = """# BHoM

The BHoM (Buildings and Habitats object Model) is an open-source AEC framework.

{wall}
"""


def splice_into_readme(readme_path: str, new_wall: str) -> bool:
    """Replace wall block in README with `new_wall`. Returns True if file changed."""
    path = Path(readme_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        new_content = BOOTSTRAP_TEMPLATE.format(wall=new_wall)
        path.write_text(new_content, encoding="utf-8")
        return True

    current = path.read_text(encoding="utf-8")
    if _WALL_BLOCK_RE.search(current):
        updated = _WALL_BLOCK_RE.sub(lambda _: new_wall, current)
    else:
        # No markers — append the wall after existing content
        sep = "" if current.endswith("\n") else "\n"
        updated = current + sep + "\n" + new_wall + "\n"

    if updated == current:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


DEFAULT_README_PATH = "profile/README.md"


def main() -> int:
    """Entrypoint. Returns exit code."""
    token = os.environ["GITHUB_TOKEN"]
    org = os.environ.get("GITHUB_ORG", "BHoM")
    readme_path = os.environ.get("README_PATH", DEFAULT_README_PATH)

    session = make_session(token)

    print(f"Listing repos in {org}...")
    repos = list_org_repos(session, org)
    print(f"Found {len(repos)} non-archived repos.")

    per_repo: list[list[dict[str, Any]]] = []
    for repo in repos:
        contributors = fetch_repo_contributors(session, org, repo["name"])
        human = filter_bots(contributors)
        print(f"  {repo['name']}: {len(human)} human contributors")
        per_repo.append(human)

    aggregated = aggregate_contributors(per_repo)
    print(f"Aggregated to {len(aggregated)} unique contributors. Enriching display names...")

    enriched = enrich_display_names(session, aggregated)
    today = date.today().isoformat()
    wall_md = render_wall(enriched, today)

    changed = splice_into_readme(readme_path, wall_md)
    if changed:
        print("README updated.")
    else:
        print("README unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
