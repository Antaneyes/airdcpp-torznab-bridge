import re
import unicodedata

SEASON_RE = re.compile(r"\b(?:S|T|Temporada|Season|Staffel|Temp|Part|Pt)\s*[._-]?\s*0?\d{1,2}\b", re.I)


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    asciiish = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", asciiish.lower()).split())


def clean_search_pattern(value: str, max_words: int | None = None) -> str:
    value = re.sub(r"\[[^]]*]|\([^)]*\)", " ", value or "")
    value = SEASON_RE.sub(" ", value)
    words = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE).split()
    return " ".join(words[:max_words] if max_words else words)


def title_roots(titles: list[str]) -> list[str]:
    roots: list[str] = []
    for title in titles:
        root = re.split(r"\s*(?::|–|—)\s*|\s+-\s+", title, maxsplit=1)[0]
        clean = clean_search_pattern(root)
        words = clean.split()
        if words and re.fullmatch(r"(?:19|20)\d{2}", words[-1]):
            words.pop()
        # Radarr elimina a veces los dos puntos de los subtítulos antes de
        # consultar el indexador: "Atlantis The Lost Empire 2001".
        if len(words) >= 3 and normalize_text(words[1]) in {"the", "el", "la", "a", "an", "un", "una"}:
            words = words[:1]
        clean = " ".join(words)
        if clean and normalize_text(clean) not in {normalize_text(value) for value in roots}:
            roots.append(clean)
    return roots


def search_variants(titles: list[str], year: str | None = None) -> list[str]:
    full_titles = [clean_search_pattern(title) for title in titles]
    full_titles = list(dict.fromkeys(title for title in full_titles if title))
    roots = title_roots(titles)
    with_year = roots + full_titles
    candidates = (
        [title if year in normalize_text(title).split() else f"{title} {year}" for title in with_year]
        if year
        else with_year
    )
    candidates.extend(roots + full_titles)
    variants: list[str] = []
    for candidate in candidates:
        if candidate and normalize_text(candidate) not in {normalize_text(value) for value in variants}:
            variants.append(candidate)
    return variants


def season_pattern(season: int) -> re.Pattern[str]:
    return re.compile(rf"\b(?:S|T|Temporada|Season|Staffel|Temp|Part|Pt)\s*[._-]?\s*0?{season}\b", re.I)


def episode_marker(value: str) -> tuple[int, int] | None:
    """Devuelve temporada/episodio para los formatos habituales de scene y carpetas."""
    normalized = normalize_text(value)
    match = re.search(r"\bs\s*0?(\d{1,2})\s*e\s*0?(\d{1,3})\b", normalized, re.I)
    if not match:
        match = re.search(r"\b0?(\d{1,2})\s*x\s*0?(\d{1,3})\b", normalized, re.I)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def detect_languages(value: str) -> list[str]:
    """Detecta solo idiomas declarados; evita inferirlos por el nombre del grupo."""
    normalized = normalize_text(value)
    tokens = normalized.split()
    languages: list[str] = []
    compact_language_pair = re.search(r"\b(?:castellanoingles|espanolingles)\b", normalized)
    technical_audio = re.compile(r"^(?:ddp?|eac3|ac3|dts|aac|opus|truehd|flac|atmos|mp3|\d(?:\.\d)?)$")

    def technical_abbreviation(abbreviation: str) -> bool:
        return any(
            token == abbreviation
            and any(technical_audio.fullmatch(candidate) for candidate in tokens[index + 1 : index + 3])
            for index, token in enumerate(tokens)
        )

    if (
        re.search(r"\b(?:spanish|espanol|castellano|spa|esp)\b", normalized)
        or re.search(r"\bdual\b", normalized)
        or compact_language_pair
        or technical_abbreviation("cast")
    ):
        languages.append("Spanish")
    if re.search(r"\b(?:english|ingles|eng)\b", normalized) or compact_language_pair or technical_abbreviation("ing"):
        languages.append("English")
    for block in re.findall(r"[\[({]([^\])}]+)[\])}]", value):
        normalized_block = normalize_text(block)
        tokens = normalized_block.split()
        technical = bool(
            re.search(r"\b(?:audio|subs?|ac3|eac3|dts|aac|opus|truehd|flac|mp3|\d[._ ]\d)\b", normalized_block)
        )
        language_list = bool(tokens) and all(token in {"es", "en"} for token in tokens)
        if not (technical or language_list):
            continue
        if re.search(r"\bes\b", normalized_block) and "Spanish" not in languages:
            languages.append("Spanish")
        if re.search(r"\ben\b", normalized_block) and "English" not in languages:
            languages.append("English")
    return languages
