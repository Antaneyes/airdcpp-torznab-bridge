import asyncio
import base64
import hashlib
import logging
import re
import time

import httpx

from app.config import Settings
from app.models import SearchResult
from app.utils.text import detect_languages, episode_marker, normalize_text, season_pattern

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
                # Los ficheros descendientes permiten demostrar que una carpeta
                # generica contiene realmente la temporada solicitada.
                query_data.update(size_min=50 * 1024 * 1024)
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
            if season is not None:
                raw = await self._inspect_ambiguous_season_folders(raw, query, season)
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
        verified_folders = self._verified_season_folders(raw, season) if season is not None else {}
        explicit_seasons = 0
        for item in raw:
            name = str(item.get("name", ""))
            raw_type = item.get("type", "file")
            item_type = str(raw_type.get("id", "file") if isinstance(raw_type, dict) else raw_type)
            size = int(float(item.get("size", 0)))
            if not name or size <= 0:
                continue
            display_name = str(item.get("_verified_display") or name)
            if season_re:
                if item_type not in {"directory", "bundle"}:
                    continue
                if not item.get("_verified_display") and not season_re.search(normalize_text(name)):
                    display_name = verified_folders.get(str(item.get("id")), "")
                    if not display_name:
                        continue
                elif season_re.search(normalize_text(name)):
                    explicit_seasons += 1
            if not season_re and extensions and item_type == "file" and not name.lower().endswith(extensions):
                continue
            tth = item.get("tth")
            users = item.get("users")
            user_count = len(users) if isinstance(users, list | dict) else int(users or 0)
            availability = max(1, int(item.get("hits", 0) or 0), user_count)
            user = item.get("users", {}).get("user", {}) if isinstance(item.get("users"), dict) else {}
            source_cid = str(user.get("cid") or "") or None
            source_hub_url = str(user.get("hub_url") or "") or None
            source_path = str(item.get("path") or "") or None
            identity = str(
                tth
                or f"{normalize_text(name)}:{size}:{item_type}:{source_cid or ''}:{normalize_text(source_path or '')}"
            )
            release_id = hashlib.sha1(identity.encode()).hexdigest()
            output.append(
                SearchResult(
                    release_id=release_id,
                    name=display_name,
                    size=size,
                    tth=tth,
                    item_type=item_type,
                    source_id=item.get("id"),
                    query=query,
                    published_at=max(0, int(float(item.get("time", 0) or 0))),
                    availability=availability,
                    source_name=name,
                    source_path=source_path,
                    source_cid=source_cid,
                    source_hub_url=source_hub_url,
                    download_via_filelist=bool(item.get("_download_via_filelist")),
                )
            )
        if season is not None:
            logger.info(
                "Temporada S%02d: explicitas=%d verificadas_por_resultados=%d verificadas_por_lista=%d salida=%d",
                season,
                explicit_seasons,
                len(verified_folders),
                sum(bool(item.get("_download_via_filelist")) for item in raw),
                len(output),
            )
        return output

    @staticmethod
    def _verified_season_folders(raw: list[dict], season: int) -> dict[str, str]:
        """Valida carpetas genericas usando los videos descendientes de la misma respuesta."""
        videos: list[tuple[dict, str, str, tuple[int, int] | None]] = []
        video_extensions = (".mkv", ".avi", ".mp4", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg")
        for child in raw:
            raw_type = child.get("type", "file")
            item_type = str(raw_type.get("id", "file") if isinstance(raw_type, dict) else raw_type)
            name = str(child.get("name") or "")
            if item_type != "file" or not name.lower().endswith(video_extensions):
                continue
            user = child.get("users", {}).get("user", {}) if isinstance(child.get("users"), dict) else {}
            videos.append((child, str(user.get("cid") or ""), str(child.get("path") or ""), episode_marker(name)))

        verified: dict[str, str] = {}
        for folder in raw:
            raw_type = folder.get("type", "directory")
            item_type = str(raw_type.get("id", "directory") if isinstance(raw_type, dict) else raw_type)
            if item_type not in {"directory", "bundle"}:
                continue
            folder_name = str(folder.get("name") or "")
            if not folder_name or season_pattern(season).search(normalize_text(folder_name)):
                continue
            user = folder.get("users", {}).get("user", {}) if isinstance(folder.get("users"), dict) else {}
            cid = str(user.get("cid") or "")
            prefix = str(folder.get("path") or "").casefold()
            descendants = [
                child
                for child, child_cid, path, marker in videos
                if cid and child_cid == cid and prefix and path.casefold().startswith(prefix) and marker is not None
            ]
            markers = [episode_marker(str(child.get("name") or "")) for child in descendants]
            if not markers or any(marker is None or marker[0] != season for marker in markers):
                continue
            episodes = sorted({marker[1] for marker in markers if marker is not None})
            if len(episodes) < 2 or episodes != list(range(1, episodes[-1] + 1)):
                continue
            declared_files = int(raw_type.get("files", 0) or 0) if isinstance(raw_type, dict) else 0
            child_size = sum(int(float(child.get("size", 0) or 0)) for child in descendants)
            folder_size = int(float(folder.get("size", 0) or 0))
            coverage = child_size / folder_size if folder_size else 0
            if declared_files != len(descendants) and coverage < 0.98:
                continue
            suffix = AirDCClient._common_technical_suffix([str(child.get("name") or "") for child in descendants])
            display = f"{folder_name} S{season:02d}"
            if suffix:
                display += f" {suffix}"
            verified[str(folder.get("id"))] = display
        return verified

    @staticmethod
    def _common_technical_suffix(names: list[str]) -> str:
        extractors = (
            ("resolution", r"\b(2160p|1080p|720p|576p|480p)\b"),
            ("source", r"\b(AMZN[ ._-]*)?(WEB[ ._-]?DL|WEBRIP|BLU[ ._-]?RAY|HDTV)\b"),
            ("audio", r"\b(EAC3|DDP|DD|AC3|DTS|AAC|TRUEHD|ATMOS)(?:[ ._-]*\d[ .]?\d)?\b"),
            ("codec", r"\b(HEVC|H[ .]?265|H[ .]?264|AVC|X265|X264)\b"),
        )
        common: list[str] = []
        for _, pattern in extractors:
            values = []
            for name in names:
                match = re.search(pattern, name, re.I)
                values.append(re.sub(r"[ ._-]+", " ", match.group(0)).strip() if match else "")
            if values and values[0] and all(normalize_text(value) == normalize_text(values[0]) for value in values):
                common.append(values[0])
        languages = [set(detect_languages(name)) for name in names]
        if languages:
            shared = set.intersection(*languages)
            if "Spanish" in shared:
                common.append("SPANISH")
            if "English" in shared:
                common.append("ENGLISH")
        return " ".join(common)

    async def _inspect_ambiguous_season_folders(
        self, raw: list[dict], query: str, season: int
    ) -> list[dict]:
        """Inspecciona listas parciales solo cuando la respuesta no demuestra el contenido."""
        already_verified = self._verified_season_folders(raw, season)
        candidates: list[dict] = []
        candidate_cids: set[str] = set()
        for item in raw:
            raw_type = item.get("type", {})
            if not isinstance(raw_type, dict) or raw_type.get("id") != "directory":
                continue
            if str(item.get("id")) in already_verified or season_pattern(season).search(str(item.get("name") or "")):
                continue
            if int(float(item.get("size", 0) or 0)) < 100 * 1024 * 1024:
                continue
            if int(raw_type.get("files", 0) or 0) < 2:
                continue
            users = item.get("users")
            user = users.get("user", {}) if isinstance(users, dict) else {}
            cid = str(user.get("cid") or "")
            if not cid or cid in candidate_cids:
                continue
            candidate_cids.add(cid)
            candidates.append(item)
            if len(candidates) >= self.settings.season_inspect_max:
                break

        semaphore = asyncio.Semaphore(3)

        async def inspect(item: dict) -> dict | None:
            async with semaphore:
                return await self._inspect_partial_filelist(item, query, season)

        enriched = list(raw)
        inspected_results = await asyncio.gather(*(inspect(item) for item in candidates))
        enriched.extend(result for result in inspected_results if result)
        logger.info(
            "Inspeccion profunda S%02d: candidatos=%d verificados=%d",
            season,
            len(candidates),
            sum(result is not None for result in inspected_results),
        )
        return enriched

    async def _inspect_partial_filelist(self, folder: dict, query: str, season: int) -> dict | None:
        users = folder.get("users")
        user = users.get("user", {}) if isinstance(users, dict) else {}
        cid = str(user.get("cid") or "")
        hub_url = str(user.get("hub_url") or "")
        root_path = str(folder.get("path") or "")
        if not cid or not hub_url or not root_path:
            return None

        opened = False
        try:
            existing = await self.http.get(f"{self.settings.airdcpp_url}/api/v1/filelists", headers=self.headers)
            existing.raise_for_status()
            if any(str(value.get("id")) == cid for value in existing.json()):
                logger.info("Inspeccion omitida cid=%s: la lista ya estaba abierta", cid)
                return None
            response = await self.http.post(
                f"{self.settings.airdcpp_url}/api/v1/filelists",
                json={"user": {"cid": cid, "hub_url": hub_url}, "directory": root_path},
                headers=self.headers,
            )
            if response.status_code == 409:
                return None
            response.raise_for_status()
            opened = True
            if not await self._wait_filelist(cid):
                return None
            items = await self._filelist_items(cid)

            # Si existe una subcarpeta de temporada, se descarga esa ruta y no
            # la raiz completa (que podria contener otras temporadas).
            target = None
            for candidate in items:
                raw_type = candidate.get("type", {})
                if isinstance(raw_type, dict) and raw_type.get("id") == "directory" and season_pattern(season).search(
                    str(candidate.get("name") or "")
                ):
                    target = candidate
                    break
            target_path = str((target or folder).get("path") or root_path)
            if target:
                changed = await self.http.post(
                    f"{self.settings.airdcpp_url}/api/v1/filelists/{cid}/directory",
                    json={"list_path": target_path},
                    headers=self.headers,
                )
                changed.raise_for_status()
                if not await self._wait_filelist(cid, target_path):
                    return None
                items = await self._filelist_items(cid)

            videos = [
                value
                for value in items
                if str(value.get("type", {}).get("id", "")) == "file"
                and str(value.get("name") or "").lower().endswith(
                    (".mkv", ".avi", ".mp4", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg")
                )
            ]
            markers = [episode_marker(str(value.get("name") or "")) for value in videos]
            if len(markers) < 2 or any(marker is None or marker[0] != season for marker in markers):
                return None
            episodes = sorted({marker[1] for marker in markers if marker})
            if episodes != list(range(1, episodes[-1] + 1)):
                return None
            selected = target or folder
            suffix = self._common_technical_suffix([str(value.get("name") or "") for value in videos])
            display = f"{folder.get('name') or query} S{season:02d}" + (f" {suffix}" if suffix else "")
            return {
                **selected,
                "id": f"filelist:{cid}:{target_path}",
                "name": str(selected.get("name") or folder.get("name") or query),
                "path": target_path,
                "users": folder.get("users"),
                "hits": folder.get("hits", 1),
                "time": selected.get("time", folder.get("time", 0)),
                "_verified_display": display,
                "_download_via_filelist": True,
            }
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            logger.info("No se pudo inspeccionar la carpeta %r: %s", folder.get("name"), exc)
            return None
        finally:
            if opened:
                try:
                    await self.http.delete(f"{self.settings.airdcpp_url}/api/v1/filelists/{cid}", headers=self.headers)
                except httpx.HTTPError:
                    logger.warning("No se pudo cerrar la lista parcial %s", cid)

    async def _wait_filelist(self, cid: str, expected_path: str | None = None) -> bool:
        deadline = time.monotonic() + self.settings.season_inspect_timeout
        while time.monotonic() < deadline:
            response = await self.http.get(
                f"{self.settings.airdcpp_url}/api/v1/filelists/{cid}", headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            location = data.get("location") or {}
            if data.get("state", {}).get("id") == "loaded" and (
                not expected_path or str(location.get("path") or "") == expected_path
            ):
                return True
            await asyncio.sleep(0.2)
        return False

    async def _filelist_items(self, cid: str) -> list[dict]:
        response = await self.http.get(
            f"{self.settings.airdcpp_url}/api/v1/filelists/{cid}/items/0/1000", headers=self.headers
        )
        response.raise_for_status()
        return list(response.json().get("items", []))

    async def download(self, release: SearchResult) -> str:
        if release.download_via_filelist:
            return await self._download_filelist_directory(release)
        return await self._search_and_download(release)

    async def _download_filelist_directory(self, release: SearchResult) -> str:
        if not all((release.source_path, release.source_cid, release.source_hub_url)):
            raise AirDCError("Faltan datos de origen para descargar la carpeta validada")
        try:
            response = await self.http.post(
                f"{self.settings.airdcpp_url}/api/v1/filelists/directory_downloads",
                json={
                    "user": {"cid": release.source_cid, "hub_url": release.source_hub_url},
                    "list_path": release.source_path,
                    "priority": 3,
                },
                headers=self.headers,
            )
            response.raise_for_status()
            download_id = str(response.json()["id"])
            deadline = time.monotonic() + self.settings.search_timeout
            while time.monotonic() < deadline:
                current = await self.http.get(
                    f"{self.settings.airdcpp_url}/api/v1/filelists/directory_downloads/{download_id}",
                    headers=self.headers,
                )
                current.raise_for_status()
                data = current.json()
                bundle = (data.get("queue_info") or {}).get("bundle") or {}
                if bundle.get("id") is not None:
                    return str(bundle["id"])
                if data.get("state") == "failed" or data.get("error"):
                    raise AirDCError(str(data.get("error") or "AirDC++ rechazó la carpeta"))
                await asyncio.sleep(0.2)
            raise AirDCError("AirDC++ no terminó de preparar la carpeta a tiempo")
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise AirDCError(f"No se pudo iniciar la descarga de la carpeta: {exc}") from exc

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
                    json={"query": {"pattern": release.tth or release.source_name or release.name}, "hub_urls": []},
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
                        user = item.get("users", {}).get("user", {}) if isinstance(item.get("users"), dict) else {}
                        source_matches = (
                            (not release.source_cid or user.get("cid") == release.source_cid)
                            and (not release.source_path or item.get("path") == release.source_path)
                        )
                        if source_matches and ((release.tth and item.get("tth") == release.tth) or (
                            int(float(item.get("size", 0))) == release.size
                            and normalize_text(item.get("name", ""))
                            == normalize_text(release.source_name or release.name)
                        )):
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
