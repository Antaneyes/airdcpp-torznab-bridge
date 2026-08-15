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


async def test_season_search_prioritizes_directories():
    hub_queries = []

    def handler(request: httpx.Request):
        path = request.url.path
        if path == "/api/v1/search" and request.method == "POST":
            return httpx.Response(200, json={"id": 42})
        if path.endswith("/hub_search"):
            hub_queries.append(request.read())
            return httpx.Response(204)
        if "/results/0/" in path:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 7,
                        "name": "Show Temporada 01",
                        "path": "/Show/Temporada 01/",
                        "size": 200,
                        "type": {"id": "directory", "files": 2},
                    }
                ],
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    client, http = make_client(handler)
    results = await client.search(["Show"], season=1)

    assert [result.name for result in results] == ["Show Temporada 01"]
    assert len(hub_queries) == 1
    assert b'"file_type":"directory"' in hub_queries[0]
    await http.aclose()


async def test_season_search_falls_back_to_all_result_types():
    hub_queries = []

    def handler(request: httpx.Request):
        path = request.url.path
        if path == "/api/v1/search" and request.method == "POST":
            return httpx.Response(200, json={"id": 42})
        if path.endswith("/hub_search"):
            hub_queries.append(request.read())
            return httpx.Response(204)
        if "/results/0/" in path:
            if len(hub_queries) == 1:
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 8,
                        "name": "Show S01",
                        "path": "/Show/S01/",
                        "size": 200,
                        "type": {"id": "directory", "files": 2},
                    }
                ],
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    client, http = make_client(handler)
    results = await client.search(["Show"], season=1)

    assert [result.name for result in results] == ["Show S01"]
    assert len(hub_queries) == 2
    assert b'"file_type":"directory"' in hub_queries[0]
    assert b'"file_type"' not in hub_queries[1]
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


def test_generic_folder_is_verified_from_descendant_episodes():
    client, _ = make_client(lambda request: httpx.Response(200))
    cid = "CID"
    parent = {
        "id": "parent",
        "name": "La casa de los espíritus (2026)",
        "path": "/Series/La casa de los espíritus (2026)/",
        "size": 800,
        "type": {"id": "directory", "directories": 1, "files": 8},
        "users": {"count": 1, "user": {"cid": cid, "hub_url": "adc://hub"}},
    }
    children = [
        {
            "id": f"episode-{episode}",
            "name": f"La casa de los espíritus.S01E{episode:02d}.1080p.WEB-DL.ESP.mkv",
            "path": f"{parent['path']}S01/episode-{episode}.mkv",
            "size": 100,
            "type": {"id": "file"},
            "users": parent["users"],
        }
        for episode in range(1, 9)
    ]

    results = client._convert_results([parent, *children], "La casa de los espíritus", 1, (".mkv",))

    assert len(results) == 1
    assert results[0].name == "La casa de los espíritus (2026) S01 1080p WEB DL SPANISH"
    assert results[0].source_name == parent["name"]
    assert results[0].source_path == parent["path"]


def test_generic_multiseason_or_incomplete_folder_is_not_a_pack():
    client, _ = make_client(lambda request: httpx.Response(200))
    parent = {
        "id": "parent",
        "name": "Show",
        "path": "/Show/",
        "size": 300,
        "type": {"id": "directory", "files": 3},
        "users": {"user": {"cid": "CID", "hub_url": "adc://hub"}},
    }
    children = [
        {
            "id": str(episode),
            "name": name,
            "path": f"/Show/{name}",
            "size": 100,
            "type": {"id": "file"},
            "users": parent["users"],
        }
        for episode, name in enumerate(("Show.S01E01.mkv", "Show.S01E03.mkv", "Show.S02E01.mkv"), 1)
    ]

    assert client._convert_results([parent, *children], "Show", 1, (".mkv",)) == []


async def test_partial_filelist_recognizes_and_downloads_nested_season():
    calls = []
    directory_download_payloads = []
    location = {"path": "/Show/", "name": "Show"}

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path == "/api/v1/filelists" and request.method == "GET":
            return httpx.Response(200, json=[])
        if path == "/api/v1/filelists" and request.method == "POST":
            return httpx.Response(200, json={"id": "CID"})
        if path == "/api/v1/filelists/CID" and request.method == "GET":
            return httpx.Response(200, json={"state": {"id": "loaded"}, "location": location})
        if path == "/api/v1/filelists/CID/directory":
            location["path"] = "/Show/S01/"
            return httpx.Response(204)
        if path == "/api/v1/filelists/CID/items/0/1000":
            if location["path"] == "/Show/":
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": 2,
                                "name": "S01",
                                "path": "/Show/S01/",
                                "size": 200,
                                "type": {"id": "directory", "files": 2},
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": episode,
                            "name": f"S01E{episode:02d}.1080p.mkv",
                            "path": f"/Show/S01/S01E{episode:02d}.1080p.mkv",
                            "size": 100,
                            "type": {"id": "file"},
                        }
                        for episode in (1, 2)
                    ]
                },
            )
        if path == "/api/v1/filelists/CID" and request.method == "DELETE":
            return httpx.Response(204)
        if path == "/api/v1/filelists/directory_downloads" and request.method == "POST":
            directory_download_payloads.append(request.read())
            return httpx.Response(200, json={"id": 55})
        if path == "/api/v1/filelists/directory_downloads/55":
            return httpx.Response(200, json={"state": "finished", "queue_info": {"bundle": {"id": 88}}})
        return httpx.Response(404)

    client, http = make_client(handler)
    folder = {
        "id": "parent",
        "name": "Show",
        "path": "/Show/",
        "size": 200,
        "type": {"id": "directory", "directories": 1, "files": 2},
        "users": {"user": {"cid": "CID", "hub_url": "adc://hub"}},
    }
    inspected = await client._inspect_partial_filelist(folder, "Show", 1)
    assert inspected is not None
    results = client._convert_results([inspected], "Show", 1, (".mkv",))
    assert results[0].name == "Show S01 1080p"
    assert results[0].source_path == "/Show/S01/"
    assert results[0].download_via_filelist
    assert await client.download(results[0]) == "88"
    assert b'"target_name":"Show S01 1080p"' in directory_download_payloads[0]
    assert b'"target_directory":"/downloads/"' in directory_download_payloads[0]
    assert ("DELETE", "/api/v1/filelists/CID") in calls
    await http.aclose()


async def test_partial_filelist_selects_only_requested_season_from_mixed_root():
    calls = []

    def video(season: int, episode: int) -> dict:
        return {
            "id": f"{season}-{episode}",
            "name": f"Show.S{season:02d}E{episode:02d}.1080p.DUAL.mkv",
            "path": f"/Show/Show.S{season:02d}E{episode:02d}.1080p.DUAL.mkv",
            "size": 100 + episode,
            "tth": f"TTH-{season}-{episode}",
            "type": {"id": "file"},
        }

    items = [*(video(1, episode) for episode in range(1, 7)), *(video(2, episode) for episode in range(1, 4))]

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path, request.content))
        path = request.url.path
        if path == "/api/v1/filelists" and request.method == "GET":
            return httpx.Response(200, json=[])
        if path == "/api/v1/filelists" and request.method == "POST":
            return httpx.Response(200, json={"id": "CID"})
        if path == "/api/v1/filelists/CID" and request.method == "GET":
            return httpx.Response(
                200,
                json={"state": {"id": "loaded"}, "location": {"path": "/Show/", "name": "Show"}},
            )
        if path == "/api/v1/filelists/CID/items/0/1000":
            return httpx.Response(200, json={"items": items})
        if path == "/api/v1/filelists/CID" and request.method == "DELETE":
            return httpx.Response(204)
        if path == "/api/v1/queue/bundles/directory" and request.method == "POST":
            return httpx.Response(200, json={"files_queued": 3, "bundle": {"id": 99}})
        return httpx.Response(404)

    client, http = make_client(handler)
    folder = {
        "id": "parent",
        "name": "Show",
        "path": "/Show/",
        "size": sum(value["size"] for value in items),
        "type": {"id": "directory", "files": len(items)},
        "users": {"user": {"cid": "CID", "hub_url": "adc://hub"}},
    }

    inspected = await client._inspect_partial_filelist(folder, "Show", 2)
    assert inspected is not None
    assert inspected["size"] == sum(100 + episode for episode in range(1, 4))
    results = client._convert_results([inspected], "Show", 2, (".mkv",))
    assert len(results) == 1
    release = results[0]
    assert release.name == "Show S02 1080p SPANISH"
    assert [value["name"] for value in release.selected_files] == [
        f"Show.S02E{episode:02d}.1080p.DUAL.mkv" for episode in range(1, 4)
    ]
    assert not release.download_via_filelist
    assert await client.download(release) == "99"
    payload = next(
        content for method, path, content in calls if method == "POST" and path == "/api/v1/queue/bundles/directory"
    )
    assert b"S01" not in payload
    assert payload.count(b"S02E") == 3
    assert b'"target_name":"Show S02 1080p SPANISH"' in payload
    assert b'"target_directory":"/downloads/"' in payload
    await http.aclose()


async def test_mixed_root_rejects_duplicate_or_gapped_requested_season():
    def handler(request: httpx.Request):
        path = request.url.path
        if path == "/api/v1/filelists" and request.method == "GET":
            return httpx.Response(200, json=[])
        if path == "/api/v1/filelists" and request.method == "POST":
            return httpx.Response(200, json={"id": "CID"})
        if path == "/api/v1/filelists/CID" and request.method == "GET":
            return httpx.Response(200, json={"state": {"id": "loaded"}, "location": {"path": "/Show/"}})
        if path == "/api/v1/filelists/CID/items/0/1000":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "name": name,
                            "path": f"/Show/{name}",
                            "size": 100,
                            "tth": f"TTH-{index}",
                            "type": {"id": "file"},
                        }
                        for index, name in enumerate(
                            ("Show.S01E01.mkv", "Show.S03E01.mkv", "Show.S03E03.mkv"), 1
                        )
                    ]
                },
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    client, http = make_client(handler)
    folder = {
        "name": "Show",
        "path": "/Show/",
        "size": 300,
        "type": {"id": "directory", "files": 3},
        "users": {"user": {"cid": "CID", "hub_url": "adc://hub"}},
    }
    assert await client._inspect_partial_filelist(folder, "Show", 3) is None
    await http.aclose()


async def test_partial_filelist_reuses_existing_list_at_same_mixed_root():
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/filelists" and request.method == "GET":
            return httpx.Response(200, json=[{"id": "CID", "location": {"path": "/Show/"}}])
        if request.url.path == "/api/v1/filelists/CID" and request.method == "GET":
            return httpx.Response(200, json={"state": {"id": "loaded"}, "location": {"path": "/Show/"}})
        if request.url.path == "/api/v1/filelists/CID/items/0/1000":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "name": f"Show.S{season:02d}E{episode:02d}.mkv",
                            "path": f"/Show/Show.S{season:02d}E{episode:02d}.mkv",
                            "size": 100,
                            "tth": f"TTH-{season}-{episode}",
                            "type": {"id": "file"},
                        }
                        for season, episode in ((1, 1), (2, 1), (2, 2))
                    ]
                },
            )
        return httpx.Response(404)

    client, http = make_client(handler)
    folder = {
        "name": "Show",
        "path": "/Show/",
        "size": 300,
        "type": {"id": "directory", "files": 3},
        "users": {"user": {"cid": "CID", "hub_url": "adc://hub"}},
    }
    inspected = await client._inspect_partial_filelist(folder, "Show", 2)
    assert inspected is not None
    assert len(inspected["_selected_files"]) == 2
    assert ("POST", "/api/v1/filelists") not in calls
    assert ("DELETE", "/api/v1/filelists/CID") not in calls
    await http.aclose()


async def test_open_filelist_location_moves_existing_session():
    requests = []

    def handler(request: httpx.Request):
        requests.append((request.method, request.url.path, request.content))
        if request.url.path == "/api/v1/filelists" and request.method == "GET":
            return httpx.Response(200, json=[{"id": "CID"}])
        if request.url.path == "/api/v1/filelists/CID/directory":
            return httpx.Response(204)
        return httpx.Response(404)

    client, http = make_client(handler)
    client.settings.airdcpp_web_url = "https://airdc.example"
    release = SearchResult(
        release_id="b" * 40,
        name="Show S01",
        size=100,
        item_type="directory",
        source_cid="CID",
        source_hub_url="adc://hub",
        source_path="/Series/Show/S01/",
    )

    assert await client.open_filelist_location(release) == "https://airdc.example/filelists/session/CID"
    assert ("POST", "/api/v1/filelists/CID/directory", b'{"list_path":"/Series/Show/S01/"}') in requests
    await http.aclose()
