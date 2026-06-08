import responses
from scripts.generate_wall_of_honour import list_org_repos
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
