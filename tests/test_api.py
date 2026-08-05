import asyncio

import httpx
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import SearchResult


def settings(tmp_path, **overrides):
    values = {
        "testing": True,
        "data_dir": tmp_path,
        "airdcpp_url": "http://airdcpp",
        "search_poll_interval": 0.1,
        "search_timeout": 2,
        "search_stable_cycles": 1,
    }
    values.update(overrides)
    return Settings(**values)


def test_health_caps_and_empty_search(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        assert client.get("/health/live").json()["status"] == "ok"
        caps = client.get("/torznab/api", params={"t": "caps"})
        assert caps.status_code == 200
        assert "<caps>" in caps.text
        result = client.get("/torznab/api", params={"t": "movie", "cat": "2000"})
        assert result.status_code == 200
        assert "Test Movie File" not in result.text
        assert "Resultado de validación" in result.text


def test_qbittorrent_login_and_upstream_failure(tmp_path):
    app = create_app(
        settings(
            tmp_path,
            testing=False,
            airdcpp_user="air",
            airdcpp_pass="pass",
            bridge_api_key="api",
            bridge_username="arr",
            bridge_password="secret",
        )
    )
    with respx.mock:
        respx.get("http://airdcpp/api/v1/queue/bundles/0/1000").mock(return_value=httpx.Response(503, text="offline"))
        with TestClient(app) as client:
            assert client.get("/api/v2/app/version").status_code == 403
            login = client.post("/api/v2/auth/login", data={"username": "arr", "password": "secret"})
            assert login.text == "Ok."
            assert client.get("/api/v2/app/version").text == "v4.3.9"
            assert client.get("/api/v2/torrents/info").status_code == 502


def test_torznab_rejects_bad_api_key(tmp_path):
    app = create_app(
        settings(
            tmp_path,
            testing=False,
            airdcpp_user="air",
            airdcpp_pass="pass",
            bridge_api_key="api",
            bridge_username="arr",
            bridge_password="secret",
        )
    )
    with TestClient(app) as client:
        response = client.get("/torznab/api", params={"t": "caps", "apikey": "bad"})
        assert response.status_code == 401
        assert "API key" in response.text


def test_browse_endpoint_requires_api_key(tmp_path):
    app = create_app(
        settings(
            tmp_path,
            testing=False,
            airdcpp_user="air",
            airdcpp_pass="pass",
            bridge_api_key="api",
            bridge_username="arr",
            bridge_password="secret",
        )
    )
    with TestClient(app) as client:
        assert client.get("/browse/missing").status_code == 401
        assert client.get("/browse/missing", params={"apikey": "api"}).status_code == 404


def test_qbittorrent_contract_and_download_lifecycle(tmp_path):
    app = create_app(settings(tmp_path))
    release = SearchResult(release_id="a" * 40, name="Movie.mkv", size=100, tth="TTH", languages=["Spanish"])
    with respx.mock:
        respx.get("http://airdcpp/api/v1/hubs").mock(return_value=httpx.Response(200, json=[]))
        respx.get("http://airdcpp/api/v1/queue/bundles/0/1000").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 88,
                        "name": "Movie.mkv",
                        "size": 100,
                        "downloaded_bytes": 100,
                        "speed": 0,
                        "seconds_left": 0,
                        "status": {"completed": True},
                        "time_finished": 10,
                    }
                ],
            )
        )
        respx.post("http://airdcpp/api/v1/search").mock(return_value=httpx.Response(200, json={"id": 42}))
        respx.post("http://airdcpp/api/v1/search/42/hub_search").mock(return_value=httpx.Response(204))
        respx.get("http://airdcpp/api/v1/search/42/results/0/1000").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": 7, "name": "Movie.mkv", "size": 100, "tth": "TTH", "type": {"id": "file"}}],
            )
        )
        respx.post("http://airdcpp/api/v1/search/42/results/7/download").mock(
            return_value=httpx.Response(200, json={"bundle_info": {"id": 88}})
        )
        respx.delete("http://airdcpp/api/v1/search/42").mock(return_value=httpx.Response(204))
        respx.post("http://airdcpp/api/v1/queue/bundles/88/remove").mock(return_value=httpx.Response(204))

        with TestClient(app) as client:
            asyncio.run(app.state.repository.save_release(release))
            assert client.get("/health/ready").status_code == 200
            redirect = client.get(f"/download/{release.release_id}.torrent", follow_redirects=False)
            assert redirect.status_code == 302
            assert "tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce" in redirect.headers["location"]
            assert client.get("/download/unknown.torrent", follow_redirects=False).status_code == 404
            assert client.get("/api/v2/app/preferences").json()["save_path"] == "/downloads"
            assert set(client.get("/api/v2/torrents/categories").json()) == {
                "radarr",
                "sonarr",
                "radarr4k",
                "sonarr4k",
            }

            magnet = f"magnet:?xt=urn:btih:{release.release_id}&dn=Movie.mkv"
            assert client.post("/api/v2/torrents/add", data={"urls": magnet, "category": "radarr"}).status_code == 200
            info = client.get("/api/v2/torrents/info", params={"category": "radarr"}).json()
            assert info[0]["state"] == "uploading"
            assert info[0]["ratio"] == 1.5
            assert info[0]["name"] == "Movie.mkv"
            assert info[0]["content_path"].endswith("/Movie.mkv")
            assert client.get("/api/v2/sync/maindata").json()["full_update"] is True
            assert client.get("/api/v2/torrents/properties", params={"hash": release.release_id}).status_code == 200
            assert client.get("/api/v2/torrents/files", params={"hash": release.release_id}).json()[0]["index"] == 0
            assert (
                client.post(
                    "/api/v2/torrents/setCategory", data={"hashes": release.release_id, "category": "sonarr"}
                ).status_code
                == 200
            )
            assert client.post("/api/v2/torrents/setShareLimits").status_code == 200
            assert client.post("/api/v2/torrents/createCategory", data={"category": "radarr4k"}).status_code == 200
            assert (
                client.post(
                    "/api/v2/torrents/delete", data={"hashes": release.release_id, "deleteFiles": "false"}
                ).status_code
                == 200
            )
            assert client.get("/api/v2/torrents/info").json() == []


def test_qbittorrent_rejects_invalid_inputs(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        assert client.post("/api/v2/torrents/add", data={}).status_code == 400
        assert client.post("/api/v2/torrents/add", data={"urls": "magnet:?xt=urn:btih:missing"}).status_code == 502
        assert client.post("/api/v2/torrents/setCategory", data={"category": "other"}).status_code == 400
        assert client.post("/api/v2/torrents/createCategory", data={"category": "other"}).status_code == 400
        assert client.get("/api/v2/torrents/properties", params={"hash": "missing"}).status_code == 404
        assert client.get("/api/v2/torrents/files", params={"hash": "missing"}).json() == []


def test_qbittorrent_categories_are_configurable_and_isolated(tmp_path):
    app = create_app(settings(tmp_path, download_categories=" radarr4k, SONARR4K,radarr4k "))
    with TestClient(app) as client:
        assert set(client.get("/api/v2/torrents/categories").json()) == {"radarr4k", "sonarr4k"}
        assert client.post("/api/v2/torrents/createCategory", data={"category": "RADARR4K"}).status_code == 200
        assert client.post("/api/v2/torrents/createCategory", data={"category": "radarr"}).status_code == 400
