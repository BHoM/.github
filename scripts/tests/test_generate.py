import tempfile
from pathlib import Path

import responses
from scripts.generate_wall_of_honour import fetch_repo_contributors, list_org_repos, filter_bots, aggregate_contributors, enrich_display_names
from scripts.github_api import make_session


@responses.activate
def test_list_org_repos_filters_archived_and_dot_github():
    responses.add(
        responses.GET,
        "https://api.github.com/orgs/BHoM/repos",
        json=[
            {"name": "BHoM", "archived": False},
            {"name": "old_repo", "archived": True},
            {"name": ".github", "archived": False},
            {"name": "BHoM_Engine", "archived": False},
        ],
        status=200,
    )
    session = make_session("fake-token")
    result = list_org_repos(session, "BHoM")
    names = [r["name"] for r in result]
    assert names == ["BHoM", "BHoM_Engine"]


@responses.activate
def test_fetch_repo_contributors_returns_list():
    responses.add(
        responses.GET,
        "https://api.github.com/repos/BHoM/BHoM_Engine/contributors",
        json=[
            {"login": "alice", "type": "User", "avatar_url": "https://x/a", "contributions": 42},
            {"login": "dependabot[bot]", "type": "Bot", "avatar_url": "https://x/d", "contributions": 5},
        ],
        status=200,
    )
    session = make_session("fake-token")
    result = fetch_repo_contributors(session, "BHoM", "BHoM_Engine")
    assert len(result) == 2
    assert result[0]["login"] == "alice"


@responses.activate
def test_fetch_repo_contributors_handles_204_empty():
    # GitHub returns 204 for an empty repo
    responses.add(
        responses.GET,
        "https://api.github.com/repos/BHoM/empty_repo/contributors",
        status=204,
    )
    session = make_session("fake-token")
    result = fetch_repo_contributors(session, "BHoM", "empty_repo")
    assert result == []


def test_filter_bots_excludes_type_bot():
    raw = [
        {"login": "alice", "type": "User"},
        {"login": "dependabot[bot]", "type": "Bot"},
    ]
    assert filter_bots(raw) == [{"login": "alice", "type": "User"}]


def test_filter_bots_excludes_bot_suffix_login_even_if_type_user():
    # Some old bot accounts have type=User but [bot] suffix
    raw = [
        {"login": "alice", "type": "User"},
        {"login": "old-tool[bot]", "type": "User"},
    ]
    assert filter_bots(raw) == [{"login": "alice", "type": "User"}]


def test_filter_bots_keeps_all_humans():
    raw = [
        {"login": "alice", "type": "User"},
        {"login": "bob", "type": "User"},
    ]
    assert filter_bots(raw) == raw


from scripts.generate_wall_of_honour import filter_denylist, DENYLISTED_LOGINS


def test_filter_denylist_excludes_known_accounts():
    raw = [
        {"login": "alice", "type": "User"},
        {"login": "BHoMBot", "type": "User"},
        {"login": "BuroHappold1", "type": "User"},
    ]
    result = filter_denylist(raw)
    assert result == [{"login": "alice", "type": "User"}]


def test_filter_denylist_keeps_unrelated_logins():
    raw = [
        {"login": "alice", "type": "User"},
        {"login": "bob", "type": "User"},
    ]
    assert filter_denylist(raw) == raw


def test_denylist_constant_includes_known_accounts():
    # Lock in the current denylist so accidental removal is caught by CI.
    assert "BHoMBot" in DENYLISTED_LOGINS
    assert "BuroHappold1" in DENYLISTED_LOGINS


def test_aggregate_single_repo():
    per_repo = [[
        {"login": "alice", "avatar_url": "https://x/a", "contributions": 10},
    ]]
    result = aggregate_contributors(per_repo)
    assert result == {
        "alice": {"avatar_url": "https://x/a", "contributions": 10}
    }


def test_aggregate_dedupes_and_sums_across_repos():
    per_repo = [
        [{"login": "alice", "avatar_url": "https://x/a", "contributions": 10}],
        [{"login": "alice", "avatar_url": "https://x/a", "contributions": 5}],
        [{"login": "bob", "avatar_url": "https://x/b", "contributions": 3}],
    ]
    result = aggregate_contributors(per_repo)
    assert result == {
        "alice": {"avatar_url": "https://x/a", "contributions": 15},
        "bob": {"avatar_url": "https://x/b", "contributions": 3},
    }


def test_aggregate_empty_input():
    assert aggregate_contributors([]) == {}
    assert aggregate_contributors([[]]) == {}


@responses.activate
def test_enrich_display_names_uses_real_name():
    responses.add(
        responses.GET,
        "https://api.github.com/users/alice",
        json={"login": "alice", "name": "Alice Example"},
        status=200,
    )
    session = make_session("fake-token")
    contributors = {"alice": {"avatar_url": "https://x/a", "contributions": 10}}
    result = enrich_display_names(session, contributors)
    assert result["alice"]["name"] == "Alice Example"


@responses.activate
def test_enrich_display_names_falls_back_to_login_when_null():
    responses.add(
        responses.GET,
        "https://api.github.com/users/bob",
        json={"login": "bob", "name": None},
        status=200,
    )
    session = make_session("fake-token")
    contributors = {"bob": {"avatar_url": "https://x/b", "contributions": 5}}
    result = enrich_display_names(session, contributors)
    assert result["bob"]["name"] == "bob"


@responses.activate
def test_enrich_display_names_falls_back_to_login_when_empty_string():
    responses.add(
        responses.GET,
        "https://api.github.com/users/carol",
        json={"login": "carol", "name": "   "},  # whitespace only
        status=200,
    )
    session = make_session("fake-token")
    contributors = {"carol": {"avatar_url": "https://x/c", "contributions": 1}}
    result = enrich_display_names(session, contributors)
    assert result["carol"]["name"] == "carol"


from scripts.generate_wall_of_honour import render_wall


def test_render_wall_empty():
    md = render_wall({}, "2026-06-08")
    assert "Wall coming soon" in md
    assert "<!-- WALL:START -->" in md
    assert "<!-- WALL:END -->" in md
    # Badge present even when empty (shows 0)
    assert "img.shields.io/badge/contributors-0-" in md
    # Last updated is italicised
    assert "_Last updated: 2026-06-08_" in md


def test_render_wall_single_row():
    contributors = {
        "alice": {"avatar_url": "https://x/a", "contributions": 10, "name": "Alice Example"},
        "bob": {"avatar_url": "https://x/b", "contributions": 5, "name": "Bob Sample"},
    }
    md = render_wall(contributors, "2026-06-08")
    # Contributor count exposed via shields.io badge instead of inline text
    assert "img.shields.io/badge/contributors-2-brightgreen" in md
    assert md.count("<tr>") == 1  # 2 cells fit in 1 row of 7
    assert "Alice Example" in md
    assert "Bob Sample" in md
    # Alphabetical: Alice before Bob
    assert md.index("Alice Example") < md.index("Bob Sample")
    # Last updated is italicised
    assert "_Last updated: 2026-06-08_" in md


def test_render_wall_two_rows_with_remainder():
    contributors = {f"user{i}": {"avatar_url": f"https://x/{i}", "contributions": 1, "name": f"User {i}"} for i in range(8)}
    md = render_wall(contributors, "2026-06-08")
    assert md.count("<tr>") == 2
    assert md.count("<td") == 8


def test_render_wall_sort_is_case_insensitive_and_unicode():
    contributors = {
        "zoe": {"avatar_url": "z", "contributions": 1, "name": "Zoe"},
        "Anna": {"avatar_url": "a", "contributions": 1, "name": "Anna"},
        "alex": {"avatar_url": "al", "contributions": 1, "name": "alex"},
        "ångström": {"avatar_url": "ang", "contributions": 1, "name": "Ångström"},
    }
    md = render_wall(contributors, "2026-06-08")
    names_in_order = []
    for name in ["alex", "Anna", "Ångström", "Zoe"]:
        names_in_order.append(md.index(name))
    assert names_in_order == sorted(names_in_order)


from scripts.generate_wall_of_honour import splice_into_readme


def test_splice_preserves_surrounding_content():
    with tempfile.TemporaryDirectory() as tmp:
        readme = Path(tmp) / "README.md"
        readme.write_text(
            "# BHoM\n\nIntro paragraph.\n\n"
            "<!-- WALL:START -->\nOLD WALL\n<!-- WALL:END -->\n\n"
            "Footer content.\n",
            encoding="utf-8",
        )
        new_wall = "<!-- WALL:START -->\nNEW WALL\n<!-- WALL:END -->"
        changed = splice_into_readme(str(readme), new_wall)
        assert changed is True
        content = readme.read_text(encoding="utf-8")
        assert "Intro paragraph." in content
        assert "Footer content." in content
        assert "NEW WALL" in content
        assert "OLD WALL" not in content


def test_splice_bootstraps_when_markers_absent():
    with tempfile.TemporaryDirectory() as tmp:
        readme = Path(tmp) / "README.md"
        readme.write_text("# BHoM\n\nIntro only.\n", encoding="utf-8")
        new_wall = "<!-- WALL:START -->\nNEW WALL\n<!-- WALL:END -->"
        changed = splice_into_readme(str(readme), new_wall)
        assert changed is True
        content = readme.read_text(encoding="utf-8")
        assert "Intro only." in content
        assert "NEW WALL" in content


def test_splice_creates_file_when_missing():
    with tempfile.TemporaryDirectory() as tmp:
        readme = Path(tmp) / "README.md"
        new_wall = "<!-- WALL:START -->\nFRESH\n<!-- WALL:END -->"
        changed = splice_into_readme(str(readme), new_wall)
        assert changed is True
        assert readme.exists()
        assert "FRESH" in readme.read_text(encoding="utf-8")


def test_splice_idempotent_no_change():
    with tempfile.TemporaryDirectory() as tmp:
        readme = Path(tmp) / "README.md"
        block = "<!-- WALL:START -->\nSAME\n<!-- WALL:END -->"
        readme.write_text(f"# BHoM\n\n{block}\n", encoding="utf-8")
        changed = splice_into_readme(str(readme), block)
        assert changed is False


from scripts.generate_wall_of_honour import main


@responses.activate
def test_main_end_to_end(monkeypatch, tmp_path):
    # Mock org repos
    responses.add(
        responses.GET,
        "https://api.github.com/orgs/BHoM/repos",
        json=[{"name": "BHoM_Engine", "archived": False}],
        status=200,
    )
    # Mock contributors
    responses.add(
        responses.GET,
        "https://api.github.com/repos/BHoM/BHoM_Engine/contributors",
        json=[
            {"login": "alice", "type": "User", "avatar_url": "https://x/a", "contributions": 10},
            {"login": "dependabot[bot]", "type": "Bot", "avatar_url": "https://x/d", "contributions": 3},
        ],
        status=200,
    )
    # Mock user details
    responses.add(
        responses.GET,
        "https://api.github.com/users/alice",
        json={"login": "alice", "name": "Alice Example"},
        status=200,
    )

    readme = tmp_path / "profile" / "README.md"
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_ORG", "BHoM")
    monkeypatch.setenv("README_PATH", str(readme))

    exit_code = main()
    assert exit_code == 0
    assert readme.exists()
    content = readme.read_text(encoding="utf-8")
    assert "Alice Example" in content
    assert "img.shields.io/badge/contributors-1-brightgreen" in content  # Only alice; bot filtered
    assert "dependabot" not in content
