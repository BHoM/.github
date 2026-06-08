# scripts/tests/test_github_api.py
import responses
from scripts.github_api import paginated_get, make_session


@responses.activate
def test_paginated_get_single_page():
    responses.add(
        responses.GET,
        "https://api.github.com/orgs/BHoM/repos",
        json=[{"name": "repo1"}, {"name": "repo2"}],
        status=200,
    )
    session = make_session("fake-token")
    result = paginated_get(session, "https://api.github.com/orgs/BHoM/repos")
    assert result == [{"name": "repo1"}, {"name": "repo2"}]


@responses.activate
def test_paginated_get_multiple_pages():
    responses.add(
        responses.GET,
        "https://api.github.com/orgs/BHoM/repos",
        json=[{"name": "repo1"}],
        status=200,
        headers={"Link": '<https://api.github.com/orgs/BHoM/repos?page=2>; rel="next"'},
    )
    responses.add(
        responses.GET,
        "https://api.github.com/orgs/BHoM/repos?page=2",
        json=[{"name": "repo2"}],
        status=200,
    )
    session = make_session("fake-token")
    result = paginated_get(session, "https://api.github.com/orgs/BHoM/repos")
    assert result == [{"name": "repo1"}, {"name": "repo2"}]


@responses.activate
def test_paginated_get_retries_on_500():
    responses.add(responses.GET, "https://api.github.com/test", status=500)
    responses.add(responses.GET, "https://api.github.com/test", json=[{"x": 1}], status=200)
    session = make_session("fake-token")
    result = paginated_get(session, "https://api.github.com/test")
    assert result == [{"x": 1}]


@responses.activate
def test_paginated_get_raises_after_3_failures():
    for _ in range(4):
        responses.add(responses.GET, "https://api.github.com/test", status=500)
    session = make_session("fake-token")
    import pytest
    with pytest.raises(Exception):
        paginated_get(session, "https://api.github.com/test")
