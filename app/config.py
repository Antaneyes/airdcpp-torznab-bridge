import os

# Configuración
AIRDCPP_URL = os.getenv("AIRDCPP_URL", "http://localhost:5600")
AIRDCPP_USER = os.getenv("AIRDCPP_USER", "")
AIRDCPP_PASS = os.getenv("AIRDCPP_PASS", "")
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")

# Constantes
KNOWN_CATEGORIES = ["airdcpp", "radarr", "sonarr", "lidarr", "readarr"]
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
HASH_FILE = os.path.join(DATA_DIR, "bridge_hashes.json")
SAVE_PATH = os.getenv("SAVE_PATH", "/downloads")

# Perfiles de filtrado por tipo de contenido
CATEGORY_PROFILES = {
    "video": {
        "extensions": ('.mkv', '.avi', '.mp4', '.m4v', '.mov', '.wmv', '.mpg', '.mpeg'),
        "min_size": 50 * 1024 * 1024, # 50MB (individual)
        "min_size_season": 100 * 1024 * 1024 # 100MB (temporada/carpeta)
    },
    "audio": {
        "extensions": ('.flac', '.mp3', '.m4a', '.wav', '.ogg', '.aac'),
        "min_size": 1 * 1024 * 1024, # 1MB
        "min_size_season": 10 * 1024 * 1024 # 10MB (álbum)
    },
    "book": {
        "extensions": ('.epub', '.pdf', '.mobi', '.azw3', '.cbr', '.cbz'),
        "min_size": 500 * 1024, # 500KB
        "min_size_season": 500 * 1024
    },
    "generic": {
        "extensions": (), # Cualquier extensión si está vacío
        "min_size": 0,
        "min_size_season": 0
    }
}

# Mapeo de categorías Torznab -> Perfil
# 2000s: Movies, 5000s: TV, 3000s: Audio, 7000s: Books, 8000s: PC/Apps
CAT_TO_PROFILE = {
    "2": "video",
    "5": "video",
    "3": "audio",
    "7": "book",
    "8": "generic"
}
