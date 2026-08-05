import logging
import re
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass
class MediaMetadata:
    titles: list[str] = field(default_factory=list)
    localized_title: str | None = None
    original_title: str | None = None
    original_language: str | None = None


class MetadataClient:
    def __init__(self, client: httpx.AsyncClient, tmdb_api_key: str = ""):
        self.client = client
        self.tmdb_api_key = tmdb_api_key
        self._cache: dict[str, MediaMetadata] = {}

    async def titles(
        self,
        query: str | None,
        imdb_id: str | None = None,
        tmdb_id: str | None = None,
        tvdb_id: str | None = None,
        media_type: str | None = None,
    ) -> list[str]:
        return (await self.details(query, imdb_id, tmdb_id, tvdb_id, media_type)).titles

    async def details(
        self,
        query: str | None,
        imdb_id: str | None = None,
        tmdb_id: str | None = None,
        tvdb_id: str | None = None,
        media_type: str | None = None,
    ) -> MediaMetadata:
        key = "|".join(str(v or "") for v in (query, imdb_id, tmdb_id, tvdb_id, media_type))
        if key in self._cache:
            return self._cache[key]
        found: list[str] = []
        tmdb = MediaMetadata()
        if self.tmdb_api_key:
            tmdb = await self._tmdb_details(query, imdb_id, tmdb_id, media_type)
            found.extend(tmdb.titles)
        if imdb_id or tvdb_id:
            found.extend(await self._tvmaze_titles(imdb_id, tvdb_id))
        if query:
            found.append(query)
        unique = list(dict.fromkeys(t.strip() for t in found if t and t.strip()))
        metadata = MediaMetadata(unique, tmdb.localized_title, tmdb.original_title, tmdb.original_language)
        self._cache[key] = metadata
        return metadata

    async def _tmdb_titles(self, imdb_id: str | None, tmdb_id: str | None, media_type: str | None) -> list[str]:
        return (await self._tmdb_details(None, imdb_id, tmdb_id, media_type)).titles

    async def _tmdb_details(
        self,
        query: str | None,
        imdb_id: str | None,
        tmdb_id: str | None,
        media_type: str | None,
    ) -> MediaMetadata:
        try:
            kind = "tv" if media_type == "tv" else "movie"
            item_id = tmdb_id
            if imdb_id:
                response = await self.client.get(
                    f"https://api.themoviedb.org/3/find/{imdb_id}",
                    params={"api_key": self.tmdb_api_key, "external_source": "imdb_id", "language": "es-ES"},
                )
                response.raise_for_status()
                payload = response.json()
                matches = payload.get("tv_results") if media_type == "tv" else payload.get("movie_results")
                matches = matches or payload.get("movie_results") or payload.get("tv_results") or []
                if not matches:
                    return MediaMetadata()
                item_id = str(matches[0]["id"])
                kind = "tv" if payload.get("tv_results") and matches is payload.get("tv_results") else "movie"
            if not item_id and query:
                year_match = re.search(r"(?:\s|\()(\d{4})(?:\)|$)", query)
                search_query = re.sub(r"\s*\(?\d{4}\)?\s*$", "", query).strip()
                params = {"api_key": self.tmdb_api_key, "query": search_query, "language": "es-ES"}
                if year_match:
                    params["year" if kind == "movie" else "first_air_date_year"] = year_match.group(1)
                search = await self.client.get(
                    f"https://api.themoviedb.org/3/search/{kind}",
                    params=params,
                )
                search.raise_for_status()
                matches = search.json().get("results", [])
                if matches:
                    item_id = str(matches[0]["id"])
            if not item_id:
                return MediaMetadata()
            response = await self.client.get(
                f"https://api.themoviedb.org/3/{kind}/{item_id}",
                params={"api_key": self.tmdb_api_key, "language": "es-ES", "append_to_response": "alternative_titles"},
            )
            response.raise_for_status()
            data = response.json()
            localized = data.get("title") or data.get("name")
            original = data.get("original_title") or data.get("original_name")
            titles = [localized, original]
            alternatives = data.get("alternative_titles", {}).get("titles", []) or data.get(
                "alternative_titles", {}
            ).get("results", [])
            titles.extend(
                (v.get("title") or v.get("name")) for v in alternatives if v.get("iso_3166_1") in {None, "ES"}
            )
            return MediaMetadata([t for t in titles if t], localized, original, data.get("original_language"))
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("No se pudieron obtener metadatos de TMDB: %s", exc)
            return MediaMetadata()

    async def _tvmaze_titles(self, imdb_id: str | None, tvdb_id: str | None) -> list[str]:
        try:
            params = {"imdb" if imdb_id else "thetvdb": imdb_id or tvdb_id}
            response = await self.client.get("https://api.tvmaze.com/lookup/shows", params=params)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            show = response.json()
            titles = [show.get("name")]
            if show.get("id"):
                aliases = await self.client.get(f"https://api.tvmaze.com/shows/{show['id']}/akas")
                aliases.raise_for_status()
                titles.extend(
                    a.get("name")
                    for a in aliases.json()
                    if not a.get("country") or a.get("country", {}).get("code") == "ES"
                )
            return [t for t in titles if t]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("No se pudieron obtener metadatos de TVMaze: %s", exc)
            return []
