import logging
import re

from app.config import Settings
from app.models import SearchResult
from app.services.airdcpp import AirDCClient
from app.services.cache import AsyncTTLCache
from app.services.database import Repository
from app.services.metadata import MediaMetadata, MetadataClient
from app.utils.text import clean_search_pattern, detect_languages, normalize_text, search_variants, title_roots

VIDEO_EXTENSIONS = (".mkv", ".avi", ".mp4", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg")
MIN_VIDEO_SIZE = 50 * 1024 * 1024
MIN_MOVIE_DIRECTORY_SIZE = 300 * 1024 * 1024
logger = logging.getLogger(__name__)


class SearchService:
    def __init__(
        self,
        airdcpp: AirDCClient,
        metadata: MetadataClient,
        repository: Repository,
        cache: AsyncTTLCache[list[SearchResult]],
        settings: Settings,
    ):
        self.airdcpp = airdcpp
        self.metadata = metadata
        self.repository = repository
        self.cache = cache
        self.settings = settings

    async def search(
        self,
        query: str | None,
        category: str | None,
        imdb_id: str | None,
        tmdb_id: str | None,
        tvdb_id: str | None,
        season: int | None,
        episode: int | None,
    ) -> list[SearchResult]:
        category_family = (category or "").split(",", maxsplit=1)[0][:1]
        if query:
            # Radarr puede repetir la misma búsqueda variando los IDs externos.
            # Compartir la entrada evita relanzar una consulta idéntica al hub.
            key = "|".join(str(value or "") for value in (normalize_text(query), category_family, season, episode))
        else:
            key = "|".join(str(value or "") for value in (category_family, imdb_id, tmdb_id, tvdb_id, season, episode))

        async def perform() -> list[SearchResult]:
            media_type = "tv" if season is not None or (category or "").startswith("5") else "movie"
            metadata = await self.metadata.details(query, imdb_id, tmdb_id, tvdb_id, media_type)
            titles = metadata.titles
            if not titles:
                return []
            year_match = re.search(r"(?:\s|\()(\d{4})(?:\)|$)", query or "")
            variants = search_variants(titles, year_match.group(1) if year_match and media_type == "movie" else None)
            if season is not None and episode is not None:
                variants = [f"{variant} S{season:02d}E{episode:02d}" for variant in variants]
            year = year_match.group(1) if year_match else None
            collected: dict[str, SearchResult] = {}
            for position, variant in enumerate(variants[: self.settings.search_max_variants], start=1):
                raw = await self.airdcpp.search([variant], season if episode is None else None, VIDEO_EXTENSIONS)
                filtered = self._filter_and_rank(raw, titles, year, season, episode, media_type)
                duplicates = 0
                for result in filtered:
                    if result.release_id in collected:
                        duplicates += 1
                    collected[result.release_id] = result
                enough = len(collected) >= self.settings.search_min_accepted_results
                logger.info(
                    "Variante %d/%d query=%r raw=%d validos=%d duplicados=%d acumulados=%d decision=%s",
                    position,
                    min(len(variants), self.settings.search_max_variants),
                    variant,
                    len(raw),
                    len(filtered),
                    duplicates,
                    len(collected),
                    "detener" if enough else "continuar",
                )
                if enough:
                    break
            filtered_results = self._filter_and_rank(
                list(collected.values()), titles, year, season, episode, media_type
            )
            results = self._deduplicate_file_directories(filtered_results)
            self._infer_languages(results, metadata)
            logger.info(
                "Deduplicacion semantica: entrada=%d salida=%d eliminados=%d",
                len(filtered_results),
                len(results),
                len(filtered_results) - len(results),
            )
            for result in results:
                await self.repository.save_release(result)
                if result.tth:
                    await self.repository.save_hash(result.tth, result.release_id)
            return results

        return await self.cache.get_or_create(key, perform)

    @staticmethod
    def _filter_and_rank(
        results: list[SearchResult],
        titles: list[str],
        year: str | None,
        season: int | None,
        episode: int | None,
        media_type: str = "movie",
    ) -> list[SearchResult]:
        full_aliases = [normalize_text(clean_search_pattern(title)) for title in titles]
        full_aliases = [re.sub(r"\b(?:19|20)\d{2}\b", "", alias).strip() for alias in full_aliases]
        full_aliases = list(dict.fromkeys(alias for alias in full_aliases if alias))
        root_aliases = [normalize_text(root) for root in title_roots(titles)]
        root_aliases = [alias for alias in root_aliases if alias not in full_aliases]
        accepted: list[tuple[int, SearchResult]] = []
        rejected = {"size": 0, "type": 0, "title": 0, "year": 0, "sequel": 0, "episode": 0}

        for result in results:
            if result.item_type not in {"file", "directory", "bundle"}:
                rejected["type"] += 1
                continue
            if result.size < MIN_VIDEO_SIZE:
                rejected["size"] += 1
                continue
            if (
                media_type == "movie"
                and result.item_type in {"directory", "bundle"}
                and result.size < MIN_MOVIE_DIRECTORY_SIZE
            ):
                rejected["size"] += 1
                continue
            words = normalize_text(result.name).split()
            matches: list[tuple[int, bool]] = []
            for alias in full_aliases + root_aliases:
                phrase = alias.split()
                matches.extend(
                    (index, alias in full_aliases)
                    for index in range(len(words) - len(phrase) + 1)
                    if words[index : index + len(phrase)] == phrase
                )
            # Los títulos deben aparecer como palabras completas y cerca del principio.
            if not matches or min(position for position, _ in matches) > 2:
                rejected["title"] += 1
                continue
            if year and year not in words:
                rejected["year"] += 1
                continue
            incompatible_number = False
            for alias in full_aliases + root_aliases:
                phrase = alias.split()
                for index in range(len(words) - len(phrase)):
                    if words[index : index + len(phrase)] != phrase:
                        continue
                    following = words[index + len(phrase)]
                    if following.isdigit() and following != year and 1 <= int(following) <= 20:
                        incompatible_number = True
            if incompatible_number:
                rejected["sequel"] += 1
                continue
            if season is not None and episode is not None:
                compact = "".join(words)
                episode_patterns = (f"s{season:02d}e{episode:02d}", f"{season}x{episode:02d}")
                if not any(pattern in compact for pattern in episode_patterns):
                    rejected["episode"] += 1
                    continue
            best_position = min(position for position, _ in matches)
            score = 100 - best_position * 10
            score += 25 if any(full for _, full in matches) else 0
            score += 10 if year and year in words else 0
            score += 4 if result.tth else 0
            score += 2 if result.item_type == "file" else 0
            accepted.append((score, result))

        accepted.sort(key=lambda pair: (-pair[0], normalize_text(pair[1].name), -pair[1].size))
        logger.info("Filtro de relevancia: raw=%d aceptados=%d descartados=%s", len(results), len(accepted), rejected)
        return [result for _, result in accepted]

    @staticmethod
    def _deduplicate_file_directories(results: list[SearchResult]) -> list[SearchResult]:
        def identity_words(name: str) -> list[str]:
            words = normalize_text(name).split()
            ignored = {"mkv", "mp4", "avi", "m4v", "mov", "wmv", "mpg", "mpeg"}
            cleaned: list[str] = []
            skip_identifier = False
            for word in words:
                if word in {"tmdb", "imdb", "tvdb"}:
                    skip_identifier = True
                    continue
                if skip_identifier and word.isdigit():
                    skip_identifier = False
                    continue
                skip_identifier = False
                if word not in ignored:
                    cleaned.append(word)
            return cleaned

        kept: list[SearchResult] = []
        for candidate in results:
            duplicate_index = None
            candidate_words = identity_words(candidate.name)
            for index, existing in enumerate(kept):
                candidate_is_file = candidate.item_type == "file"
                existing_is_file = existing.item_type == "file"
                if candidate_is_file == existing_is_file:
                    continue
                tolerance = max(1024 * 1024, int(max(candidate.size, existing.size) * 0.002))
                if abs(candidate.size - existing.size) > tolerance:
                    continue
                existing_words = identity_words(existing.name)
                shorter, longer = sorted((candidate_words, existing_words), key=len)
                if longer[: len(shorter)] == shorter:
                    duplicate_index = index
                    break
            if duplicate_index is None:
                kept.append(candidate)
                continue
            existing = kept[duplicate_index]
            if candidate.tth and not existing.tth:
                kept[duplicate_index] = candidate
        return kept

    @staticmethod
    def _infer_languages(results: list[SearchResult], metadata: MediaMetadata) -> None:
        language_names = {
            "en": "English",
            "es": "Spanish",
            "ja": "Japanese",
            "fr": "French",
            "de": "German",
            "it": "Italian",
            "pt": "Portuguese",
            "ko": "Korean",
            "zh": "Chinese",
        }
        localized = normalize_text(metadata.localized_title or "")
        original = normalize_text(metadata.original_title or "")
        localized_is_distinct = bool(localized and original and localized != original)
        localized_words = localized.split()

        for result in results:
            languages = detect_languages(result.name)
            words = normalize_text(result.name).split()
            localized_match = localized_is_distinct and any(
                words[index : index + len(localized_words)] == localized_words
                for index in range(min(3, len(words) - len(localized_words) + 1))
            )
            if localized_match and "Spanish" not in languages:
                languages.append("Spanish")
            if localized_match and re.search(r"\bmulti\b", normalize_text(result.name)):
                original_language = language_names.get(metadata.original_language or "")
                if original_language and original_language not in languages:
                    languages.append(original_language)
            result.languages = languages
