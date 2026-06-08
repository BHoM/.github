import responses
from scripts.generate_wall_of_honour import fetch_repo_contributors, list_org_repos, filter_bots, aggregate_contributors
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
