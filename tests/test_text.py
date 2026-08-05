from app.utils.text import (
    clean_search_pattern,
    detect_languages,
    normalize_text,
    search_variants,
    season_pattern,
    strip_diacritics,
    title_roots,
)


def test_normalization_and_variants():
    assert normalize_text("La Casa de Papel") == "la casa de papel"
    assert clean_search_pattern("Show.Name (2024) [WEB] S01") == "Show Name"
    assert strip_diacritics("Qué vida más triste") == "Que vida mas triste"
    assert search_variants(["Qué vida más triste"]) == ["Qué vida más triste", "Que vida mas triste"]
    assert search_variants(["Película Larga"], "2024") == [
        "Película Larga 2024",
        "Pelicula Larga 2024",
        "Película Larga",
        "Pelicula Larga",
    ]
    assert title_roots(["Atlantis: El imperio perdido", "Atlantis: The Lost Empire"]) == ["Atlantis"]
    assert title_roots(["Atlantis The Lost Empire 2001"]) == ["Atlantis"]
    assert search_variants(["Atlantis: El imperio perdido", "Atlantis: The Lost Empire"], "2001")[:3] == [
        "Atlantis 2001",
        "Atlantis El imperio perdido 2001",
        "Atlantis The Lost Empire 2001",
    ]
    flattened = search_variants(["Atlantis The Lost Empire 2001"], "2001")
    assert flattened[:2] == ["Atlantis 2001", "Atlantis The Lost Empire 2001"]
    assert all("2001 2001" not in variant for variant in flattened)
    assert season_pattern(1).search("Serie Temporada 01 1080p")
    assert detect_languages("Es por tu bien (2024)") == []
    assert detect_languages("Érase una vez en América (1984)") == []
    assert detect_languages("Movie [es Opus 5.1, en Opus 5.1]") == ["Spanish", "English"]
    assert detect_languages("Movie [es, es, en]") == ["Spanish", "English"]
    assert detect_languages("Movie [Cast DDP 5.1 Ing DD 5.1]") == ["Spanish", "English"]
    assert detect_languages("Movie [CastellanoInglés EAC3 5.1]") == ["Spanish", "English"]
    assert detect_languages("The Cast (2024) 1080p") == []
    assert detect_languages("Ingmar Bergman Collection") == []
