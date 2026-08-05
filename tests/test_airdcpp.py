import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.models import SearchResult
from app.services.airdcpp import AirDCClient, AirDCError


def make_client(handler):
    settings = Settings(
        testing=True,
        airdcpp_url="http://airdcpp",
        airdcpp_user="user",
        airdcpp_pass=SecretStr("pass"),
        search_poll_interval=0.1,
        search_timeout=2,
        search_stable_cycles=1,
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AirDCClient(http, settings), http


async def test_search_download_remove_and_health():
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path == "/api/v1/hubs":
            return httpx.Response(200, json=[])
        if path == "/api/v1/queue/bundles/0/1000":
            return httpx.Response(200, json=[{"id": 8}])
        if path == "/api/v1/search" and request.method == "POST":
            return httpx.Response(200, json={"id": 42})
        if path.endswith("/hub_search"):
            return httpx.Response(204)
        if "/results/0/" in path:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 7,
                        "name": "Movie.mkv",
                        "size": 100,
                        "tth": "TTH",
                        "time": 1_403_129_739,
                        "hits": 4,
                        "users": [{"id": 1}, {"id": 2}],
                        "type": {"id": "file"},
                    }
                ],
            )
        if path.endswith("/results/7/download"):
            return httpx.Response(200, json={"bundle_info": {"id": 88}})
        if path.endswith("/remove"):
            return httpx.Response(204)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    client, http = make_client(handler)
    assert await client.ready()
    assert await client.bundles() == [{"id": 8}]
    results = await client.search(["Movie"], extensions=(".mkv",))
    assert len(results) == 1
    assert results[0].release_id == "17d8237ade22d05e21505732053a860b4ab71de7"
    assert results[0].published_at == 1_403_129_739
    assert results[0].availability == 4
    release = SearchResult(release_id="a" * 40, name="Movie.mkv", size=100, tth="TTH")
    assert await client.download(release) == "88"
    await client.remove_bundle("88")
    assert ("DELETE", "/api/v1/search/42") in calls
    await http.aclose()


async def test_upstream_failures_are_explicit():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("offline", request=request)

    client, http = make_client(handler)
    assert not await client.ready()
    with pytest.raises(AirDCError):
        await client.bundles()
    with pytest.raises(AirDCError):
        await client.search(["Movie"])
    await http.aclose()


def test_result_filters_seasons_extensions_and_invalid_items():
    client, _ = make_client(lambda request: httpx.Response(200))
    raw = [
        {"id": 1, "name": "Show Temporada 01", "size": 200, "type": {"id": "directory"}},
        {"id": 2, "name": "Show Temporada 02", "size": 200, "type": {"id": "directory"}},
        {"id": 3, "name": "tiny.mkv", "size": 0, "tth": "BAD"},
    ]
    results = client._convert_results(raw, "Show", 1, (".mkv",))
    assert [r.name for r in results] == ["Show Temporada 01"]
    assert results[0].tth is None
