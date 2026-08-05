import asyncio
import base64
import hashlib
import logging
import time

import httpx

from app.config import Settings
from app.models import SearchResult
from app.utils.text import normalize_text, season_pattern

logger = logging.getLogger(__name__)


class AirDCError(RuntimeError):
    pass


class AirDCClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings):
        self.http = http
        self.settings = settings
        self.search_semaphore = asyncio.Semaphore(settings.airdcpp_max_active_searches)

    @property
    def headers(self) -> dict[str, str]:
        token = base64.b64encode(
            f"{self.settings.airdcpp_user}:{self.settings.airdcpp_pass.get_secret_value()}".encode()
        ).decode()
        return {"Authorization": f"Basic {token}"}

    async def ready(self) -> bool:
        try:
            response = await self.http.get(f"{self.settings.airdcpp_url}/api/v1/hubs", headers=self.headers)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def bundles(self) -> list[dict]:
        try:
            response = await self.http.get(
                f"{self.settings.airdcpp_url}/api/v1/queue/bundles/0/1000", headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AirDCError(f"No se pudo consultar la cola de AirDC++: {exc}") from exc

    async def search(
        self, variants: list[str], season: int | None = None, extensions: tuple[str, ...] = ()
    ) -> list[SearchResult]:
        collected: dict[str, SearchResult] = {}
        async with self.search_semaphore:
            for variant in variants:
                for result in await self._search_once(variant, season, extensions):
                    existing = collected.get(result.release_id)
                    if not existing or len(result.name) > len(existing.name):
                        collected[result.release_id] = result
                if collected:
                    break
        return list(collected.values())

    async def _search_once(self, query: str, season: int | None, extensions: tuple[str, ...]) -> list[SearchResult]:
        instance_id: str | int | None = None
        try:
            response = await self.http.post(f"{self.settings.airdcpp_url}/api/v1/search", json={}, headers=self.headers)
            response.raise_for_status()
            instance_id = response.json()["id"]
            query_data: dict[str, object] = {"pattern": query}
            if season is not None:
                query_data.update(type_id="directory", size_min=100 * 1024 * 1024)
            response = await self.http.post(
                f"{self.settings.airdcpp_url}/api/v1/search/{instance_id}/hub_search",
                json={"query": query_data, "hub_urls": []},
                headers=self.headers,
            )
            response.raise_for_status()
            deadline = time.monotonic() + self.settings.search_timeout
            raw: list[dict] = []
            previous = -1
            stable = 0
            while time.monotonic() < deadline:
                await asyncio.sleep(self.settings.search_poll_interval)
                response = await self.http.get(
                    f"{self.settings.airdcpp_url}/api/v1/search/{instance_id}/results/0/{self.settings.search_max_results}",
                    headers=self.headers,
                )
                response.raise_for_status()
                raw = response.json()
                if raw and len(raw) == previous:
                    stable += 1
                    if stable >= self.settings.search_stable_cycles:
                        break
                else:
                    stable = 0
                previous = len(raw)
            return self._convert_results(raw, query, season, extensions)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise AirDCError(f"Falló la búsqueda '{query}': {exc}") from exc
        finally:
            if instance_id is not None:
                try:
                    await self.http.delete(
                        f"{self.settings.airdcpp_url}/api/v1/search/{instance_id}", headers=self.headers
                    )
                except httpx.HTTPError:
                    logger.warning("No se pudo eliminar la búsqueda AirDC++ %s", instance_id)

    def _convert_results(
        self, raw: list[dict], query: str, season: int | None, extensions: tuple[str, ...]
    ) -> list[SearchResult]:
        output: list[SearchResult] = []
        season_re = season_pattern(season) if season is not None else None
        for item in raw:
            name = str(item.get("name", ""))
            raw_type = item.get("type", "file")
            item_type = str(raw_type.get("id", "file") if isinstance(raw_type, dict) else raw_type)
            size = int(float(item.get("size", 0)))
            if not name or size <= 0:
                continue
            if season_re and (item_type not in {"directory", "bundle"} or not season_re.search(normalize_text(name))):
                continue
            if not season_re and extensions and item_type == "file" and not name.lower().endswith(extensions):
                continue
            tth = item.get("tth")
            users = item.get("users")
            user_count = len(users) if isinstance(users, list | dict) else int(users or 0)
            availability = max(1, int(item.get("hits", 0) or 0), user_count)
            identity = str(tth or f"{normalize_text(name)}:{size}:{item_type}")
            release_id = hashlib.sha1(identity.encode()).hexdigest()
            output.append(
                SearchResult(
                    release_id=release_id,
                    name=name,
                    size=size,
                    tth=tth,
                    item_type=item_type,
                    source_id=item.get("id"),
                    query=query,
                    published_at=max(0, int(float(item.get("time", 0) or 0))),
                    availability=availability,
                )
            )
        return output

    async def download(self, release: SearchResult) -> str:
        return await self._search_and_download(release)

    async def _search_and_download(self, release: SearchResult) -> str:
        async with self.search_semaphore:
            instance_id = None
            try:
                created = await self.http.post(
                    f"{self.settings.airdcpp_url}/api/v1/search", json={}, headers=self.headers
                )
                created.raise_for_status()
                instance_id = created.json()["id"]
                await self.http.post(
                    f"{self.settings.airdcpp_url}/api/v1/search/{instance_id}/hub_search",
                    json={"query": {"pattern": release.tth or release.name}, "hub_urls": []},
                    headers=self.headers,
                )
                deadline = time.monotonic() + self.settings.search_timeout
                selected = None
                while time.monotonic() < deadline and selected is None:
                    await asyncio.sleep(self.settings.search_poll_interval)
                    response = await self.http.get(
                        f"{self.settings.airdcpp_url}/api/v1/search/{instance_id}/results/0/{self.settings.search_max_results}",
                        headers=self.headers,
                    )
                    response.raise_for_status()
                    for item in response.json():
                        if (release.tth and item.get("tth") == release.tth) or (
                            int(float(item.get("size", 0))) == release.size
                            and normalize_text(item.get("name", "")) == normalize_text(release.name)
                        ):
                            selected = item
                            break
                if not selected:
                    raise AirDCError("No se encontró una fuente exacta para la descarga")
                response = await self.http.post(
                    f"{self.settings.airdcpp_url}/api/v1/search/{instance_id}/results/{selected['id']}/download",
                    json={"priority": 3},
                    headers=self.headers,
                )
                response.raise_for_status()
                return str(response.json()["bundle_info"]["id"])
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise AirDCError(f"No se pudo iniciar la descarga: {exc}") from exc
            finally:
                if instance_id is not None:
                    try:
                        await self.http.delete(
                            f"{self.settings.airdcpp_url}/api/v1/search/{instance_id}", headers=self.headers
                        )
                    except httpx.HTTPError:
                        pass

    async def remove_bundle(self, bundle_id: str, delete_files: bool = False) -> None:
        # La API de AirDC++ retira la entrada de la cola. El bridge nunca borra el path directamente.
        response = await self.http.post(
            f"{self.settings.airdcpp_url}/api/v1/queue/bundles/{bundle_id}/remove",
            json={"remove_finished": bool(delete_files and self.settings.allow_file_delete)},
            headers=self.headers,
        )
        if response.status_code not in {200, 204, 404}:
            raise AirDCError(f"AirDC++ rechazó la retirada del bundle {bundle_id}: HTTP {response.status_code}")
