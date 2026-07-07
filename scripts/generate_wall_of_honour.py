"""Generate BHoM Wall of Honour and splice into profile/README.md."""
from __future__ import annotations

import json
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
    """List repos in `org`, excluding the org's `.github` repo.

    Archived repos are included so their contributors stay on the wall.
    """
    url = f"{GITHUB_API}/orgs/{org}/repos"
    all_repos = paginated_get(session, url, params={"per_page": 100, "type": "all"})
    return [r for r in all_repos if r["name"] != ".github"]


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


# Logins to exclude from the wall: org automation accounts and shared admin
# accounts that don't carry a [bot] suffix or type=Bot in the API.
# Add new entries here if a future refresh surfaces another non-human.
DENYLISTED_LOGINS = frozenset({
    "BHoMBot",       # BHoM org automation bot
    "BuroHappold1",  # shared "Administrator" account
})


def filter_denylist(contributors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove contributors whose login is in DENYLISTED_LOGINS."""
    return [c for c in contributors if c["login"] not in DENYLISTED_LOGINS]


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


def _contributors_badge(count: int) -> str:
    color = "lightgrey" if count == 0 else "brightgreen"
    # HTML img rather than markdown ![]() so it renders inside the <p> wrapper
    return (
        f"<img alt=\"Contributors\" src=\"https://img.shields.io/badge/contributors-{count}-{color}"
        "?style=flat-square&logo=github&logoColor=white\" />"
    )


def render_wall(contributors: dict[str, dict[str, Any]], last_updated: str) -> str:
    """Render the markdown block (markers included) for the wall."""
    badge = _contributors_badge(len(contributors))

    if not contributors:
        return (
            "<!-- WALL:START -->\n"
            "<h2 align=\"center\">Our Contributors</h2>\n\n"
            f"<p align=\"center\">{badge}</p>\n\n"
            "Wall coming soon. No contributors yet.\n\n"
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
        "<h2 align=\"center\">Our Contributors</h2>\n\n"
        f"<p align=\"center\">{badge}</p>\n\n"
        "<p align=\"center\">Thank you to everyone who has contributed to the BHoM.</p>\n\n"
        "<table>\n"
        + "\n".join(rows)
        + "\n</table>\n\n"
        f"_Last updated: {last_updated}_\n"
        "<!-- WALL:END -->"
    )


def _render_cell(login: str, info: dict[str, Any]) -> str:
    name = info["name"]
    cell_width = f"{100 / GRID_COLS:.2f}%"
    # Request the avatar at 2x display size so it stays sharp on hi-DPI screens
    return (
        f"    <td align=\"center\" valign=\"top\" width=\"{cell_width}\">\n"
        f"      <a href=\"https://github.com/{login}\" title=\"@{login}\">"
        f"<img src=\"https://github.com/{login}.png?size={AVATAR_SIZE * 2}\" "
        f"width=\"{AVATAR_SIZE}\" height=\"{AVATAR_SIZE}\" alt=\"{name}\" /><br/>"
        f"<sub><b>{name}</b></sub></a>\n"
        "    </td>"
    )


DEFAULT_ROSTER_PATH = "profile/wall_roster.json"


def load_roster(roster_path: str) -> dict[str, dict[str, Any]]:
    """Load the persisted roster; missing file means an empty roster."""
    path = Path(roster_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_roster(roster_path: str, roster: dict[str, dict[str, Any]]) -> None:
    """Write the roster as stable, diff-friendly JSON."""
    path = Path(roster_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(roster, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def merge_into_roster(
    roster: dict[str, dict[str, Any]],
    live: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Union live contributors into the roster. Live data wins; absent logins persist.

    Denylisted logins are dropped even if a past run added them.
    """
    merged = {
        login: {"name": info["name"]}
        for login, info in roster.items()
        if login not in DENYLISTED_LOGINS
    }
    for login, info in live.items():
        merged[login] = {"name": info["name"]}
    return merged


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
        # No markers found; append the wall after existing content
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
    roster_path = os.environ.get("ROSTER_PATH", DEFAULT_ROSTER_PATH)

    session = make_session(token)

    print(f"Listing repos in {org}...")
    repos = list_org_repos(session, org)
    print(f"Found {len(repos)} non-archived repos.")

    per_repo: list[list[dict[str, Any]]] = []
    for repo in repos:
        contributors = fetch_repo_contributors(session, org, repo["name"])
        human = filter_denylist(filter_bots(contributors))
        print(f"  {repo['name']}: {len(human)} human contributors")
        per_repo.append(human)

    aggregated = aggregate_contributors(per_repo)
    print(f"Aggregated to {len(aggregated)} unique contributors. Enriching display names...")

    enriched = enrich_display_names(session, aggregated)

    roster = load_roster(roster_path)
    merged = merge_into_roster(roster, enriched)
    save_roster(roster_path, merged)
    print(f"Roster: {len(roster)} known, {len(merged)} after merge.")

    today = date.today().isoformat()
    wall_md = render_wall(merged, today)

    changed = splice_into_readme(readme_path, wall_md)
    if changed:
        print("README updated.")
    else:
        print("README unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
