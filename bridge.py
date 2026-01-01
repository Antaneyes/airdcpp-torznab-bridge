import os
import time
import uuid
import requests
import json
import base64
import email.utils
import xml.sax.saxutils as saxutils
import hashlib
import xml.etree.ElementTree as ET
import unicodedata
import threading
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import JSONResponse
from typing import Optional

app = FastAPI(title="AirDC++ Torznab/qBit Bridge")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    host = request.headers.get("host", "localhost:8000")
    print(f">>> REQ: {request.method} {request.url} (Host header: {host})")
    if request.query_params:
        print(f"    Params: {dict(request.query_params)}")
    
    response = await call_next(request)
    print(f"<<< RES: {response.status_code} for {request.url.path}")
    return response

@app.get("/health")
async def health():
    return {"status": "ok", "hashes": len(HASH_MAP_TTH_TO_HEX)}

# Configuración
AIRDCPP_URL = os.getenv("AIRDCPP_URL", "http://localhost:5600")
AIRDCPP_USER = os.getenv("AIRDCPP_USER", "")
AIRDCPP_PASS = os.getenv("AIRDCPP_PASS", "")
TMDB_API_KEY = "f637fd7b5ef5b4c62249b8d67122a0f6"

SESSION_TOKEN = None

# Persistencia de Hashes TTH <-> Hex y Bundle IDs
HASH_FILE = "/app/data/bridge_hashes.json"
HASH_MAP_TTH_TO_HEX = {}
HASH_MAP_HEX_TO_TTH = {}
BUNDLE_MAP_ID_TO_TTH = {}  # Mapeo de AirDC++ Bundle ID -> TTH
BUNDLE_MAP_ID_TO_CAT = {}  # Mapeo de AirDC++ Bundle ID -> Categoría (radarr/sonarr)
FINISHED_BUNDLES_CACHE = {} # Mapeo de TTH -> Bundle Info finalizado
TITLE_CACHE = {} # Mapeo de ID -> [Nombres]
KNOWN_CATEGORIES = ["airdcpp", "radarr", "sonarr"] # Categorías permitidas en Radarr/Sonarr

# Semáforo para limitar búsquedas simultáneas en AirDC++ (1 por sesión para evitar kicks)
GLOBAL_SEARCH_LOCK = threading.Semaphore(1)
# Lock para proteger la escritura del archivo de hashes
FILE_LOCK = threading.Lock()

def load_hashes():
    global HASH_MAP_TTH_TO_HEX, HASH_MAP_HEX_TO_TTH, BUNDLE_MAP_ID_TO_TTH, FINISHED_BUNDLES_CACHE
    
    # --- LÓGICA DE MIGRACIÓN Y PROTECCIÓN ---
    OLD_PATH = "/app/bridge_hashes.json"
    
    # 1. Si HASH_FILE es una carpeta (fallo de Docker), lo ignoramos para no crashear
    if os.path.isdir(HASH_FILE):
        print(f"ALERTA: '{HASH_FILE}' es una carpeta (posible error de montaje Docker). Usando ruta interna temporal.")
        temp_path = "/app/bridge_hashes_backup.json"
        
        # Intentar migrar desde la vieja si existe
        if os.path.isfile(OLD_PATH) and not os.path.exists(temp_path):
            import shutil
            shutil.copy(OLD_PATH, temp_path)
            print("INFO: Datos migrados de la ruta antigua a ruta temporal.")
            
        load_from_path(temp_path)
        return

    # 2. Migración normal del archivo suelto a la nueva carpeta /data/
    if not os.path.exists(HASH_FILE) and os.path.isfile(OLD_PATH):
        try:
            os.makedirs(os.path.dirname(HASH_FILE), exist_ok=True)
            import shutil
            shutil.copy(OLD_PATH, HASH_FILE)
            print(f"INFO: Se han migrado los hashes automáticamente desde {OLD_PATH}")
        except Exception as e:
            print(f"AVISO: No se pudo migrar automáticamente: {e}")

    load_from_path(HASH_FILE)

def load_from_path(path):
    global HASH_MAP_TTH_TO_HEX, HASH_MAP_HEX_TO_TTH, BUNDLE_MAP_ID_TO_TTH, FINISHED_BUNDLES_CACHE
    if os.path.exists(path) and os.path.isfile(path):
        try:
            with open(path, "r") as f:
                content = f.read().strip()
                if not content: content = "{}"
                data = json.loads(content)
                
                if "hashes" in data:
                    HASH_MAP_TTH_TO_HEX = data.get("hashes", {})
                    BUNDLE_MAP_ID_TO_TTH = data.get("bundles", {})
                    BUNDLE_MAP_ID_TO_CAT = data.get("categories", {})
                    FINISHED_BUNDLES_CACHE = data.get("finished", {})
                else:
                    HASH_MAP_TTH_TO_HEX = data
                
                HASH_MAP_HEX_TO_TTH = {v: k for k, v in HASH_MAP_TTH_TO_HEX.items()}
                print(f"INFO: Carga completada desde {path}: {len(HASH_MAP_TTH_TO_HEX)} hashes.")
        except Exception as e:
            print(f"ERROR: No se pudo leer {path}: {e}")

def save_hashes():
    with FILE_LOCK:
        try:
            # Asegurar que el directorio de datos existe
            os.makedirs(os.path.dirname(HASH_FILE), exist_ok=True)
            data = {
                "hashes": HASH_MAP_TTH_TO_HEX,
                "bundles": BUNDLE_MAP_ID_TO_TTH,
                "categories": BUNDLE_MAP_ID_TO_CAT,
                "finished": FINISHED_BUNDLES_CACHE
            }
            with open(HASH_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"ERROR: No se pudo guardar el archivo de hashes: {e}")

def get_hex_hash(tth):
    if not tth:
        print("DEBUG: get_hex_hash recibió un TTH vacío o None.")
        return ""
    
    if tth in HASH_MAP_TTH_TO_HEX:
        return HASH_MAP_TTH_TO_HEX[tth]
    
    new_hex = hashlib.sha1(tth.encode()).hexdigest()
    HASH_MAP_TTH_TO_HEX[tth] = new_hex
    HASH_MAP_HEX_TO_TTH[new_hex] = tth
    save_hashes()
    return new_hex

load_hashes()

def get_auth_headers():
    if AIRDCPP_USER and AIRDCPP_PASS:
        auth_str = f"{AIRDCPP_USER}:{AIRDCPP_PASS}"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()
        return {"Authorization": f"Basic {encoded_auth}"}
            
    return {}

def normalize_text(text):
    """Elimina acentos y caracteres especiales de un texto."""
    if not text: return ""
    # Normalizar a NFD para separar caracteres de acentos
    text = unicodedata.normalize('NFD', text)
    # Filtrar solo caracteres que no sean acentos (Mn = Mark, Nonspacing)
    text = "".join([c for c in text if unicodedata.category(c) != 'Mn'])
    return text.lower().strip()

def clean_search_pattern(text):
    """Limpia un nombre complejo para hacerlo más apto para búsqueda en el Hub."""
    import re
    if not text: return ""
    
    # 1. Quitar contenido entre corchetes y paréntesis (tags, años, etc)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    
    # 2. Reemplazar puntos, guiones bajos y guiones por espacios
    text = text.replace(".", " ").replace("_", " ").replace("-", " ")
    
    # 3. Quitar indicadores de temporada (problemáticos para búsqueda literal)
    text = re.sub(r'\b(Temporada|Season|Staffel|Temp|Part|Pt|S|T)\s*\d+\b', '', text, flags=re.IGNORECASE)
    
    # 4. Quitar tags comunes de release
    text = re.sub(r'\b(NF|WEB-DL|HMAX|DSNP|AMZN|AVC|DD\+|Atmos|HDO|1080p|720p|x264|x265|HEVC|Dual|PACK)\b', '', text, flags=re.IGNORECASE)
    
    # 5. Quedarse con las primeras 4 palabras (título base)
    words = text.split()
    clean = " ".join(words[:4]).strip()
    
    # Si la limpieza ha borrado TODO, devolvemos las primeras palabras del original
    if not clean and words:
        return " ".join(words[:3]) or text
        
    return clean

@app.on_event("startup")
def startup_event():
    print(f"--- Iniciando Test de Conectividad ---")
    print(f"Objetivo: {AIRDCPP_URL}")
    headers = get_auth_headers()
    try:
        print("> Enviando petición GET a /api/v1/hubs...")
        r = requests.get(f"{AIRDCPP_URL}/api/v1/hubs", headers=headers, timeout=2)
        print(f"> Respuesta recibida: {r.status_code}")
        if r.status_code == 200:
            print("INFO: Conexión con AirDC++ establecida correctamente.")
        else:
            print(f"ALERTA: AirDC++ respondió con status {r.status_code}. Revisa credenciales.")
    except Exception as e:
        print(f"ERROR: No se pudo contactar con AirDC++. Detalles: {e}")
    print("--- Test de Conectividad Finalizado ---")

@app.get("/api")
@app.get("/torznab")
@app.get("/torznab/api")
def torznab_api(
    request: Request,
    t: str, 
    q: Optional[str] = None, 
    cat: Optional[str] = None,
    imdbid: Optional[str] = None,
    tmdbid: Optional[str] = None,
    tvdbid: Optional[str] = None,
    rid: Optional[str] = None,
    season: Optional[str] = None,
    ep: Optional[str] = None,
    apikey: Optional[str] = None
):
    # Log detallado de búsqueda para depuración
    print(f"> Torznab API request (t={t}): q='{q}', cat={cat}, season={season}, ep={ep}, imdb={imdbid}, tmdb={tmdbid}, tvdb={tvdbid}")
    
    if t == "caps":
        return Response(content=get_caps_xml().strip(), media_type="application/xml")
    if t in ["search", "tvsearch", "movie", "movie-search"]:
        # 0. Detectar año y LIMPIAR patrones de temporada
        detected_year = None
        if q and q.lower() != "none":
            import re
            # Busca un año de 4 dígitos entre espacios o paréntesis al final
            year_match = re.search(r'(?:\s|\()(\d{4})(?:\)|$)', q)
            if year_match:
                detected_year = year_match.group(1)
                print(f"DEBUG: Año detectado por regex en query: {detected_year}")
            
            # IMPORTANTE: Si es búsqueda de TV, quitamos patrones tipo S01, T01 para que el Hub encuentre de todo
            if t == "tvsearch" or (cat and cat.startswith("5")):
                q_old = q
                q = re.sub(r'\s[ST]\d{1,2}\b.*', '', q, flags=re.IGNORECASE).strip()
                if q != q_old:
                    print(f"DEBUG: Query TV limpiada de temporada: '{q_old}' -> '{q}'")

        # 1. Recolectar nombres base (Original + Traducidos)
        base_names = []
        if imdbid or tvdbid or tmdbid:
            base_names.extend(resolve_titles_by_id(imdbid=imdbid, tvdbid=tvdbid, tmdbid=tmdbid))
        
        if q and q.lower() != "none":
            if not base_names:
                base_names.extend(resolve_titles_by_name(q))
            if q not in base_names: base_names.append(q)

        # 2. Dedulplicar nombres base preservando caracteres (ñ, acentos)
        unique_bases = []
        seen_lowers = set()
        for name in base_names:
            low = name.lower().strip()
            if low and low not in seen_lowers:
                unique_bases.append(name.strip())
                seen_lowers.add(low)

        if not unique_bases:
             print(f">>> AVISO: Búsqueda sin nombres resolubles (t={t}). Cancelando.")
             return Response(content=get_test_xml().strip(), media_type="application/xml")

        # 3. Formatear queries finales (Temporada/Episodio/Año)
        final_queries = []
        is_season_search = (season is not None and ep is None)
        
        for base in unique_bases:
            if season and ep:
                final_queries.append(f"{base} S{season.zfill(2)}E{ep.zfill(2)}")
            elif season:
                final_queries.append(base)
            else:
                is_movie = (t in ["movie", "movie-search"] or (cat and cat.startswith("2")))
                if detected_year and is_movie:
                    if not base.endswith(detected_year):
                        final_queries.append(f"{base} {detected_year}")
                    final_queries.append(base)
                else:
                    final_queries.append(base)

        # 4. Dedulplicar queries finales (orden preservado)
        dedup_queries = []
        for fq in final_queries:
            if fq not in dedup_queries:
                dedup_queries.append(fq)
            
        with GLOBAL_SEARCH_LOCK:
            results = search_airdcpp(dedup_queries, is_season_search=is_season_search, season_num=season)
        
        # Construimos el base_url
        host = request.headers.get("host", "localhost:8000")
        scheme = request.url.scheme
        base_url = f"{scheme}://{host}"
        
        xml_content = format_torznab_results(results, base_url, season=season, ep=ep).strip()
        return Response(content=xml_content, media_type="application/xml")
    
    return Response(content="<error code='200' description='Not implemented' />", media_type="application/xml")

def get_test_xml():
    now_rfc = email.utils.formatdate(usegmt=True)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed" version="2.0">
<channel>
    <title>AirDC++ Bridge Test</title>
    <description>AirDC++ Torznab Bridge Feed</description>
    <language>en-us</language>
    <category>2000</category>
    <item>
        <title>Test Movie File 1080p.mkv</title>
        <guid isPermaLink="false">MOVIEHASH123</guid>
        <pubDate>{now_rfc}</pubDate>
        <size>2147483648</size>
        <link>magnet:?xt=urn:btih:6363636363636363636363636363636363636363&amp;dn=MovieTest</link>
        <enclosure url="http://localhost:8000/download/6363636363636363636363636363636363636363.torrent" length="2147483648" type="application/x-bittorrent" />
        <torznab:attr name="category" value="2000"/>
        <torznab:attr name="size" value="2147483648"/>
        <torznab:attr name="infohash" value="6363636363636363636363636363636363636363"/>
        <torznab:attr name="seeders" value="50"/>
        <torznab:attr name="peers" value="10"/>
    </item>
</channel>
</rss>"""

def get_caps_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<caps>
    <server version="1.0" title="AirDC++ Bridge" />
    <limits max="100" default="50" />
    <registration status="no" open="yes" />
    <searching>
        <search available="yes" supportedParams="q,imdbid,tmdbid" />
        <tv-search available="yes" supportedParams="q,season,ep,imdbid,tvdbid" />
        <movie-search available="yes" supportedParams="q,imdbid,tmdbid" />
    </searching>
    <categories>
        <category id="2000" name="Movies">
            <subcat id="2040" name="HD" />
        </category>
        <category id="5000" name="TV">
            <subcat id="5040" name="HD" />
        </category>
    </categories>
</caps>"""

def resolve_titles_by_id(imdbid=None, tvdbid=None, tmdbid=None):
    """Consulta nombres alternativos por ID priorizando TMDB (para español) y usando TVMaze como fallback."""
    key = imdbid or (f"tvdb_{tvdbid}" if tvdbid else None) or (f"tmdb_{tmdbid}" if tmdbid else None)
    if not key: return []
    
    if key in TITLE_CACHE:
        return TITLE_CACHE[key]
    
    titles = []
    
    # 1. Intentar TMDB primero (Mucho mejor para español)
    if TMDB_API_KEY:
        titles = resolve_titles_via_tmdb(imdbid=imdbid, tmdbid=tmdbid)
        if titles:
            print(f"> TMDB encontró nombres para {key}: {titles}")
            
    # 2. Usar TVMaze para obtener más alias o si TMDB falló
    try:
        url = ""
        if imdbid:
            url = f"https://api.tvmaze.com/lookup/shows?imdb={imdbid}"
        elif tvdbid:
            url = f"https://api.tvmaze.com/lookup/shows?thetvdb={tvdbid}"
            
        if url:
            print(f"> Consultando TVMaze para ID: {key} (Complemento)")
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                tvmaze_titles = extract_titles_from_tvmaze_show(data)
                # Añadir los que no tengamos ya
                for t in tvmaze_titles:
                    if t not in titles:
                        titles.append(t)
            elif r.status_code == 404 and (imdbid or tvdbid):
                print(f"> ID {key} no encontrado en TVMaze.")
    except Exception as e:
        print(f"Error resolviendo títulos por ID en TVMaze: {e}")
        
    if titles:
        # Poner los títulos de TMDB (probablemente español) al principio
        TITLE_CACHE[key] = titles
            
    return titles

def resolve_titles_via_tmdb(imdbid=None, tmdbid=None, query=None, year=None):
    """Consulta nombres en español usando TheMovieDB (TMDB)."""
    if not TMDB_API_KEY: return []
    
    titles = []
    try:
        base_url = "https://api.themoviedb.org/3"
        r = None
        
        if tmdbid:
            # Búsqueda directa por ID de TMDB (peli o serie)
            r = requests.get(f"{base_url}/movie/{tmdbid}?api_key={TMDB_API_KEY}&language=es-ES&append_to_response=alternative_titles,translations", timeout=5)
            if r.status_code != 200:
                r = requests.get(f"{base_url}/tv/{tmdbid}?api_key={TMDB_API_KEY}&language=es-ES&append_to_response=alternative_titles,translations", timeout=5)
        elif imdbid:
            # Búsqueda por External ID (IMDB)
            find_url = f"{base_url}/find/{imdbid}?api_key={TMDB_API_KEY}&language=es-ES&external_source=imdb_id"
            fr = requests.get(find_url, timeout=5)
            if fr.status_code == 200:
                fdata = fr.json()
                results = fdata.get("movie_results", []) or fdata.get("tv_results", [])
                if results:
                    show_id = results[0]["id"]
                    is_tv = "tv_results" in fdata and fdata["tv_results"]
                    type_str = "tv" if is_tv else "movie"
                    r = requests.get(f"{base_url}/{type_str}/{show_id}?api_key={TMDB_API_KEY}&language=es-ES&append_to_response=alternative_titles,translations", timeout=5)
        elif query:
            # Búsqueda por nombre. Si hay año, ayuda mucho a la precisión.
            search_params = {
                "api_key": TMDB_API_KEY,
                "language": "es-ES",
                "query": query,
                "include_adult": "false"
            }
            if year:
                # Probamos primero como película con año
                search_url = f"{base_url}/search/movie"
                search_params["primary_release_year"] = year
                sr = requests.get(search_url, params=search_params, timeout=5)
                if sr.status_code == 200 and sr.json().get("results"):
                    results = sr.json()["results"]
                else:
                    # Si falla o no hay resultados, probamos multi-search (incluye series)
                    search_url = f"{base_url}/search/multi"
                    if "primary_release_year" in search_params: del search_params["primary_release_year"]
                    search_params["query"] = f"{query} {year}"
                    sr = requests.get(search_url, params=search_params, timeout=5)
                    results = sr.json().get("results", [])
            else:
                search_url = f"{base_url}/search/multi"
                sr = requests.get(search_url, params=search_params, timeout=5)
                results = sr.json().get("results", [])

            if results:
                show_id = results[0]["id"]
                media_type = results[0].get("media_type", "movie")
                r = requests.get(f"{base_url}/{media_type}/{show_id}?api_key={TMDB_API_KEY}&language=es-ES&append_to_response=alternative_titles,translations", timeout=5)

        if r and r.status_code == 200:
            data = r.json()
            # 1. Nombre principal en español
            name = data.get("title") or data.get("name")
            if name: titles.append(name)
            
            # 2. Títulos alternativos en España (Solo Castellano)
            alt = data.get("alternative_titles", {})
            alt_list = alt.get("titles", []) or alt.get("results", [])
            for a in alt_list:
                # Solo queremos títulos de España que sean en castellano (es)
                # Ignoramos ca (catalán), eu (euskera), gl (gallego)
                if a.get("iso_3166_1") == "ES":
                    # TMDB a veces no da el iso_639_1 en alternative_titles, 
                    # pero si no lo da, solemos confiar en que el principal es es.
                    lang = a.get("iso_639_1", "es") 
                    if lang == "es":
                        t = a.get("title") or a.get("name")
                        if t and t not in titles: titles.append(t)
            
            # 3. Traducciones (Solo Castellano)
            trans = data.get("translations", {}).get("translations", [])
            for tr in trans:
                if tr.get("iso_3166_1") == "ES" and tr.get("iso_639_1") == "es":
                    t = tr.get("data", {}).get("title") or tr.get("data", {}).get("name")
                    if t and t not in titles: titles.append(t)
            
            print(f"> TMDB resolvió para '{query or tmdbid or imdbid}' (Filtrado Español): {titles}")
    except Exception as e:
        print(f"Error en TMDB: {e}")
        
    return titles

def resolve_titles_by_name(query):
    """Intenta encontrar una serie/peli por nombre y sacar sus AKAs."""
    import re
    # 1. Limpiar el nombre y detectar año
    year_match = re.search(r'\s(\d{4})$', query)
    detected_year = year_match.group(1) if year_match else None
    
    clean_q = query.split("(")[0].strip()
    clean_q = re.sub(r'\s\d{4}$', '', clean_q).strip()
    
    if clean_q in TITLE_CACHE:
        return TITLE_CACHE[clean_q]
        
    # 1. Intentar TMDB primero si hay KEY (es mucho mejor para pelis)
    if TMDB_API_KEY:
        titles = resolve_titles_via_tmdb(query=clean_q, year=detected_year)
        if titles:
            TITLE_CACHE[clean_q] = titles
            return titles

    # 2. Si no hay TMDB o falló, vamos a TVMaze
    titles = []
    try:
        print(f"> Buscando en TVMaze por nombre: '{clean_q}'")
        url = f"https://api.tvmaze.com/singlesearch/shows?q={clean_q}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            titles = extract_titles_from_tvmaze_show(data)
    except Exception as e:
        print(f"Error resolviendo títulos por nombre: {e}")

    if titles:
        print(f"> Títulos encontrados por nombre para '{clean_q}': {titles}")
        TITLE_CACHE[clean_q] = titles
    
    # 2. Si es una película (probablemente cat=2000) o si lo que encontramos 
    # en TVMaze parece ser una serie irrelevante (por el ":") mientras que el original no,
    # intentamos una traducción simple para "adivinar" el nombre en español.
    
    is_series_match = titles and ":" in titles[0] and ":" not in clean_q
    
    if not titles or is_series_match:
        guess = translate_title_to_spanish(clean_q)
        if guess and guess.lower() != clean_q.lower():
            if guess not in titles:
                print(f"> Agregando adivinanza en español: '{guess}'")
                titles.append(guess)
                TITLE_CACHE[clean_q] = titles
            
    return titles

def translate_title_to_spanish(text):
    """Fallback simple usando MyMemory (Gratuito/Sin Key) para adivinar el nombre en español."""
    try:
        url = f"https://api.mymemory.translated.net/get?q={text}&langpair=en|es"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            data = r.json()
            translated = data.get("responseData", {}).get("translatedText")
            if translated and len(translated) > 1:
                # Limpiar posibles restos
                return translated.replace('"', '').replace("'", "").strip()
    except:
        pass
    return None

def extract_titles_from_tvmaze_show(show_data):
    """Extrae nombre principal y AKAs de un objeto show de TVMaze, priorizando español."""
    spanish_titles = []
    other_titles = []
    try:
        main_name = show_data.get("name")
        if main_name:
            other_titles.append(main_name)
        
        show_id = show_data.get("id")
        if show_id:
            ak_res = requests.get(f"https://api.tvmaze.com/shows/{show_id}/akas", timeout=5)
            if ak_res.status_code == 200:
                akas = ak_res.json()
                for ak in akas:
                    name = ak.get("name")
                    if not name: continue
                    
                    # Priorizamos alias en español
                    if (ak.get("country") or {}).get("code") == "ES":
                        if name not in spanish_titles:
                            spanish_titles.append(name)
                    elif not ak.get("country"): # Alias general
                        if name not in other_titles and name not in spanish_titles:
                            other_titles.append(name)
    except Exception as e:
        print(f"Error extrayendo títulos: {e}")
    
    # Devolver la lista con español primero para que el bridge lo busque antes
    return spanish_titles + [t for t in other_titles if t not in spanish_titles]

def search_airdcpp(query_or_list, is_season_search=False, season_num=None):
    import re
    from concurrent.futures import ThreadPoolExecutor
    headers = get_auth_headers()
    
    # Preparamos el regex para filtrar por temporada si es necesario
    season_regex = None
    if is_season_search and season_num:
        s_int = int(season_num)
        # Patrón mejorado: T1, S1, Season 1, Temporada 1, Temp 1, Pt 1, Part 1
        pattern = rf'(?:[ST]|Temporada|Season|Staffel|Temp|Pt|Part|P)\s*[.\-_]?\s*0?{s_int}\b'
        season_regex = re.compile(pattern, re.IGNORECASE)
        print(f"> Filtro regex para temporada {season_num} activado: {pattern}")
    
    # query_or_list puede ser un string (viejo) o una lista de strings (nuevo)
    queries_to_try = []
    if isinstance(query_or_list, str):
        queries_to_try = [query_or_list]
    else:
        queries_to_try = query_or_list

    # Expandir con fallbacks (quitar año) para cada query
    expanded_queries = []
    for q in queries_to_try:
        if not q: continue
        expanded_queries.append(q)
        match_year = re.search(r'\s(\d{4})$', q)
        if match_year:
            base_no_year = q.replace(match_year.group(0), "").strip()
            if base_no_year not in expanded_queries:
                expanded_queries.append(base_no_year)
            
    # Eliminar duplicados manteniendo orden
    final_queries = []
    for q in expanded_queries:
        if q not in final_queries:
            final_queries.append(q)

    print(f"--- Iniciando búsqueda AirDC++ con {len(final_queries)} variantes en paralelo ---")

    all_results = []
    
    def search_variant(q_attempt):
        variant_results = []
        try:
            print(f"> Lanzando búsqueda paralela: '{q_attempt}'")
            # 1. Crear instancia de búsqueda
            res = requests.post(f"{AIRDCPP_URL}/api/v1/search", json={}, headers=headers, timeout=10)
            res.raise_for_status()
            instance_id = res.json()["id"]
            
            # 2. Lanzar la búsqueda real
            query_data = {"pattern": q_attempt}
            if is_season_search:
                query_data["type_id"] = "directory"
                query_data["size_min"] = 1024 * 1024 * 1024 # 1GB
            
            search_payload = {"query": query_data, "hub_urls": []}
            hub_res = requests.post(f"{AIRDCPP_URL}/api/v1/search/{instance_id}/hub_search", json=search_payload, headers=headers, timeout=10)
            hub_res.raise_for_status()
            
            # 3. Polling optimizado (cada 1s, máx 15s)
            raw_results = []
            max_results = 2000
            last_stable_count = -1
            stable_cycles = 0
            
            for i in range(15):
                time.sleep(1)
                try:
                    results_res = requests.get(f"{AIRDCPP_URL}/api/v1/search/{instance_id}/results/0/{max_results}", headers=headers, timeout=5)
                    if results_res.status_code == 200:
                        current_results = results_res.json()
                        current_count = len(current_results)
                        raw_results = current_results
                        
                        # Lógica de estabilidad: salir solo si el conteo se mantiene igual 
                        # durante al menos 4 segundos (ciclos) y tenemos algún resultado.
                        if current_count > 0:
                            if current_count == last_stable_count:
                                stable_cycles += 1
                            else:
                                stable_cycles = 0
                                
                            if stable_cycles >= 4:
                                print(f"  -> Búsqueda estabilizada en {current_count} resultados.")
                                break
                        
                        last_stable_count = current_count
                except Exception:
                    continue
            
            print(f"  -> '{q_attempt}': {len(raw_results)} resultados brutos encontrados.")
            
            # 4. Limpiar instancia inmediatamente
            requests.delete(f"{AIRDCPP_URL}/api/v1/search/{instance_id}", headers=headers, timeout=5)
            
            # 5. Filtrar resultados de esta variante
            video_extensions = ('.mkv', '.avi', '.mp4', '.m4v', '.mov', '.wmv', '.mpg', '.mpeg')
            min_size = 100 * 1024 * 1024 if is_season_search else 50 * 1024 * 1024
            has_ep_pattern = re.search(r'[Ss]\d{2}[Ee]\d{2}', q_attempt)
            
            for r in raw_results:
                name_raw = r["name"]
                name_lower = name_raw.lower()
                name_norm = normalize_text(name_raw)
                
                raw_type = r.get("type", "file")
                item_type = raw_type.get("id", "file") if isinstance(raw_type, dict) else str(raw_type)
                size_bytes = int(r["size"])
                
                if is_season_search:
                    if item_type not in ["directory", "bundle"]: continue
                    clean_name = name_norm.replace("-", " ").replace(".", " ").replace("_", " ")
                    
                    if season_regex:
                        if not season_regex.search(clean_name):
                            # print(f"DEBUG: Descartado por temporada: {name_raw}")
                            continue
                    
                    # Formato para Sonarr: Inyectamos el SXX después del título de la serie para que sea estándar
                    s_num = str(season_num or "").zfill(2)
                    display_season_tag = f"S{s_num}"
                    series_name = final_queries[0]
                    
                    name_lower = name_raw.lower()
                    series_lower = series_name.lower()
                    
                    # Regex para detectar el tag de temporada redundante (S7, T7, Temporada 7...)
                    s_clean_pattern = rf'(?:[ST]|Temporada|Season|Staffel|Temp|Pt|Part|P)\s*[.\-_]?\s*0?{season_num}\b'

                    # Ver si el nombre del hub ya contiene ALGUNA de las variantes buscadas (español o inglés)
                    matched_alias = None
                    for q in final_queries:
                        if q.lower() in name_lower:
                            matched_alias = q
                            break

                    if matched_alias:
                        # Si ya tiene un nombre de serie (sea cual sea), solo nos aseguramos de que tenga el SXX
                        if display_season_tag.lower() in name_lower:
                            display_name = name_raw
                        else:
                            # Inyectar SXX tras el alias encontrado (+ año si existe)
                            alias_lower = matched_alias.lower()
                            idx = name_lower.find(alias_lower) + len(alias_lower)
                            
                            # Si sigue el año "(2019)", lo incluimos en el prefijo
                            year_match = re.search(r'^\s*\(?\d{4}\)?', name_raw[idx:])
                            if year_match:
                                idx += len(year_match.group(0))
                            
                            prefix = name_raw[:idx].strip()
                            suffix = name_raw[idx:].strip()
                            
                            # Limpiar de la parte restante cualquier tag de temporada REDUNDANTE
                            suffix = re.sub(s_clean_pattern, '', suffix, flags=re.IGNORECASE).strip()
                            suffix = re.sub(r'^[\s.\-_]+', '', suffix) # Limpiar conectores
                            
                            if suffix:
                                display_name = f"{prefix} {display_season_tag} {suffix}"
                            else:
                                display_name = f"{prefix} {display_season_tag}"
                    else:
                        # Si no coincide con ninguna variante conocida (ej: nombre genérico o alias raro)
                        # Prependemos la primera variante (título principal)
                        name_cleaned = re.sub(s_clean_pattern, '', name_raw, flags=re.IGNORECASE).strip()
                        name_cleaned = re.sub(r'^[\s.\-_]+', '', name_cleaned)
                        
                        if name_cleaned:
                            # Si tiene info extra, la conservamos
                            display_name = f"{final_queries[0]} {display_season_tag} - {name_raw}"
                        else:
                            # Era solo un tag de temporada genérico
                            display_name = f"{final_queries[0]} {display_season_tag}"
                else:
                    if not name_lower.endswith(video_extensions): continue
                    display_name = name_raw
                
                if size_bytes < min_size: continue
                if has_ep_pattern and has_ep_pattern.group(0).lower() not in name_lower.replace(".", " ").replace("-", " "): continue
                
                # VALIDACIÓN / GENERACIÓN DE TTH
                tth = r.get("tth")
                if not tth:
                    if item_type in ["directory", "bundle"]:
                        # Usar el nombre de pantalla (que incluye la serie) para el TTH sintético 
                        # Esto ayuda al fallback de búsqueda en qbit_add
                        tth = f"SYNTH:{display_name}:{size_bytes}"
                        print(f"DEBUG: Generado TTH sintético para carpeta: {tth}")
                    else:
                        print(f"DEBUG: Saltando archivo '{display_name}' por TTH vacío.")
                        continue
                        
                variant_results.append({"name": display_name, "size": size_bytes, "tth": tth})
                
        except Exception as e:
            print(f"Error en variante '{q_attempt}': {e}")
        return variant_results

    # Ejecución paralela con STAGGER (retraso entre lanzamientos)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for q in final_queries:
            futures.append(executor.submit(search_variant, q))
            # Retraso crucial para que el HUB no nos ignore
            time.sleep(2.5) 

    # Recolectar resultados conforme terminan
    for f in futures:
        try:
            res_list = f.result()
            all_results.extend(res_list)
        except Exception as e:
            print(f"Error recuperando resultados de futuro: {e}")

    # Eliminar duplicados por TTH
    unique_results = []
    seen_tths = set()
    for r in all_results:
        if r["tth"] not in seen_tths:
            unique_results.append(r)
            seen_tths.add(r["tth"])
            
    print(f"--- Búsqueda finalizada: {len(unique_results)} resultados únicos totales ---")
    return unique_results

            
    # Eliminar duplicados por TTH
    unique_results = []
    seen_tths = set()
    for r in final_results:
        if r["tth"] not in seen_tths:
            unique_results.append(r)
            seen_tths.add(r["tth"])
            
    print(f"--- Búsqueda finalizada: {len(unique_results)} resultados únicos totales ---")
    return unique_results

def format_torznab_results(results, base_url, season=None, ep=None):
    timestamp = time.time() - 10800
    now_rfc = email.utils.formatdate(timestamp, usegmt=True)
    base_url = str(base_url).rstrip("/")
    
    # Usamos ET para un XML perfecto
    import xml.etree.ElementTree as ET
    
    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:torznab", "http://torznab.com/schemas/2015/feed")
    channel = ET.SubElement(rss, "channel")
    
    ET.SubElement(channel, "title").text = "AirDC++ Bridge Results"
    ET.SubElement(channel, "description").text = "AirDC++ Torznab Bridge Feed"
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "category").text = "2000"
    
    for res in results:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = res['name']
        
        fake_hash = get_hex_hash(res['tth'])
        
        # URL de descarga real (HTTP) con extensión fake para felicidad de Radarr
        download_url = f"{base_url}/download/{fake_hash}.torrent?name={saxutils.quoteattr(res['name'])[1:-1]}"
        # Añadimos un tracker dummy para que Radarr no se queje si el DHT está desactivado
        fake_magnet = f"magnet:?xt=urn:btih:{fake_hash}&dn={saxutils.quoteattr(res['name'])[1:-1]}&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
        
        ET.SubElement(item, "link").text = fake_magnet
        ET.SubElement(item, "description").text = "AirDC++ Result"
        guid = ET.SubElement(item, "guid")
        guid.text = fake_hash
        guid.set("isPermaLink", "false")
        
        enclosure = ET.SubElement(item, "enclosure")
        enclosure.set("url", download_url)
        enclosure.set("length", str(int(float(res['size']))))
        enclosure.set("type", "application/x-bittorrent")
        
        ET.SubElement(item, "pubDate").text = now_rfc
        
        # Atributos Torznab
        lang = "English"
        if any(x in res['name'].lower() for x in ["spanish", "español", "esp", "spa", " es ", ".es.", "castellano", "hdo", "tland", "hdzero", "microhd", "dual", "multi"]):
            lang = "Spanish"
            
        attrs = [
            ("category", "5000" if season else "2000"),
            ("size", str(int(float(res['size'])))),
            ("infohash", fake_hash),
            ("magneturl", fake_magnet),
            ("language", lang),
            ("seeders", "100"),
            ("peers", "10")
        ]
        
        if season:
            attrs.append(("season", season))
        if ep:
            attrs.append(("episode", ep))
        
        for name, val in attrs:
            attr = ET.SubElement(item, "{http://torznab.com/schemas/2015/feed}attr")
            attr.set("name", name)
            attr.set("value", val)
            
    return ET.tostring(rss, encoding="unicode", method="xml")

@app.get("/download/{fake_hash}")
@app.get("/download/{fake_hash}.torrent") # Soportar ambas formas
async def download_redirect(fake_hash: str, name: str = "file"):
    from fastapi.responses import RedirectResponse
    print(f">>> Radarr GRAB detectado para: {name} (Hex: {fake_hash})")
    
    # Strip .torrent if present
    if fake_hash.endswith(".torrent"):
        fake_hash = fake_hash[:-8]
        
    tth = HASH_MAP_HEX_TO_TTH.get(fake_hash, fake_hash)
    # También aquí para consistencia
    magnet = f"magnet:?xt=urn:btih:{fake_hash}&dn={name}&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
    
    # Redirección 301 (Permanente) para máxima compatibilidad con el grabber de Radarr
    return RedirectResponse(url=magnet, status_code=301)

# --- Módulo de Emulación qBittorrent ---

@app.get("/api/v2/app/version")
@app.get("/version/api")  # Alias para algunos clientes
async def qbit_version():
    return Response(content="v4.3.9", media_type="text/plain")

@app.get("/api/v2/app/webApiVersion")
@app.get("/api/v2/app/webapiVersion") # Alias minúscula (Radarr lo pide así)
async def qbit_webapi_version():
    return Response(content="2.8.2", media_type="text/plain")

@app.post("/api/v2/auth/login")
@app.post("/api/v2/auth/login/") # Con slash por si acaso
async def qbit_login(response: Response):
    # Radarr/Sonarr necesitan el Set-Cookie SID para considerar el login válido
    response.set_cookie(key="SID", value="fake-session-id-12345")
    return Response(content="Ok.", media_type="text/plain")

@app.get("/api/v2/app/preferences")
async def qbit_preferences():
    # Algunos clientes piden preferencias durante el test inicial
    return {
        "save_path": "/downloads",
        "listen_port": 8000
    }

@app.get("/api/v2/sync/maindata")
async def qbit_maindata(category: Optional[str] = None):
    # Radarr pide esto frecuentemente. Devolver la lista de torrents.
    torrents = {}
    qbit_list = qbit_info(category=category)
    for t in qbit_list:
        torrents[t["hash"]] = t
        
    return {
        "torrents": torrents, 
        "full_update": True, 
        "categories": {cat: {"name": cat, "savePath": "/downloads"} for cat in KNOWN_CATEGORIES}
    }

@app.get("/api/v2/torrents/categories")
async def qbit_categories():
    return {cat: {"name": cat, "savePath": "/downloads"} for cat in KNOWN_CATEGORIES}

@app.post("/api/v2/torrents/createCategory")
async def qbit_create_category():
    return Response(content="Ok.", media_type="text/plain")

@app.post("/api/v2/torrents/setCategory")
async def qbit_set_category():
    return Response(content="Ok.", media_type="text/plain")

@app.get("/api/v2/torrents/properties")
async def qbit_properties(hash: str):
    # Dummy properties para Radarr
    return {
        "save_path": "/downloads",
        "creation_date": int(time.time()),
        "piece_size": 16384,
        "is_seed": True,
        "total_size": 0, # Se podría mejorar buscando el size real
    }

@app.get("/api/v2/torrents/files")
async def qbit_files(hash: str):
    # Radarr necesita la lista de archivos para saber qué importar.
    # Como AirDC++ no nos da esto fácilmente en un solo paso tras finalizar, 
    # devolvemos el archivo principal basado en el nombre del bundle.
    
    headers = get_auth_headers()
    tth = HASH_MAP_HEX_TO_TTH.get(hash, hash)
    
    # Intentamos buscar el bundle en la cola para sacar el size exacto
    r = requests.get(f"{AIRDCPP_URL}/api/v1/queue/bundles/0/1000", headers=headers, timeout=5)
    size = 0
    name = "unknown_file"
    if r.status_code == 200:
        for b in r.json():
            bundle_id = str(b["id"])
            if BUNDLE_MAP_ID_TO_TTH.get(bundle_id) == tth:
                size = int(float(b["size"]))
                name = b["name"]
                break
    
    # Si no está en la cola, al menos devolvemos una estructura válida
    return [{
        "name": name,
        "size": size,
        "progress": 1.0,
        "priority": 1,
        "is_seed": True,
        "piece_range_start": 0,
        "piece_range_end": 1,
        "availability": 1.0
    }]

@app.post("/api/v2/torrents/delete")
async def qbit_delete(hash: str = Query(None), hashes: str = Query(None)):
    # Radarr pide borrar el "torrent" cuando termina de importarlo.
    # Limpiamos nuestro cache para que deje de aparecer en Radarr.
    target_hashes = []
    if hash: target_hashes.append(hash)
    if hashes: target_hashes.extend(hashes.split('|'))
    
    for h in target_hashes:
        tth = HASH_MAP_HEX_TO_TTH.get(h)
        if tth and tth in FINISHED_BUNDLES_CACHE:
            print(f"INFO: Borrando {h} de FINISHED_BUNDLES_CACHE (Radarr terminó)")
            del FINISHED_BUNDLES_CACHE[tth]
            save_hashes()
            
    return Response(content="Ok.", media_type="text/plain")

@app.get("/api/v2/torrents/info")
def qbit_info(category: Optional[str] = None):
    headers = get_auth_headers()
    try:
        # Consultamos la cola de AirDC++
        r = requests.get(f"{AIRDCPP_URL}/api/v1/queue/bundles/0/1000", headers=headers, timeout=5)
        bundles_in_queue = []
        if r.status_code == 200:
            bundles_in_queue = r.json()
        
        qbit_results = []
        reported_tths = set()
        
        # Normalizar categoría solicitada
        req_cat = category.lower() if category else None
        
        # 1. Procesar bundles activos en la cola
        needs_save = False
        for b in bundles_in_queue:
            bundle_id = str(b["id"])
            tth = BUNDLE_MAP_ID_TO_TTH.get(bundle_id)
            if not tth: continue
            
            # FILTRO DE CATEGORÍA
            bundle_cat = BUNDLE_MAP_ID_TO_CAT.get(bundle_id, "radarr").lower()
            if req_cat and bundle_cat != req_cat:
                continue
                
            reported_tths.add(tth)
            fake_hash = get_hex_hash(tth)
            size = int(float(b["size"]))
            downloaded = int(float(b.get("downloaded_bytes", 0)))
            progress = downloaded / size if size > 0 else 0
            
            status_obj = b.get("status", {})
            is_completed = status_obj.get("completed", False) or progress >= 0.999 # Usar pequeño epsilon
            
            # Log de estado para depuración
            print(f"DEBUG status ({b['name']}): Progress={progress:.4f}, Status={status_obj.get('str', 'N/A')}, Completed={is_completed}")
            
            target_path = b.get("target", "").rstrip("/")
            if target_path:
                save_path, _ = os.path.split(target_path)
            else:
                save_path = "/downloads"
            
            # Timestamp de finalización estable
            completion_time = int(b.get("time_finished", 0))
            if is_completed and completion_time == 0:
                 completion_time = int(time.time())

            res_item = {
                "hash": fake_hash,
                "name": b["name"],
                "size": size,
                "progress": progress,
                "dlspeed": int(float(b.get("speed", 0))),
                "eta": int(float(b.get("seconds_left", 864000))),
                "state": "uploading" if is_completed else "downloading",
                "amount_left": max(0, size - downloaded),
                "completed": completion_time if is_completed else 0,
                "save_path": save_path,
                "label": bundle_cat,
                "category": bundle_cat,
                "num_seeds": 1 if is_completed else 0,
                "num_leechs": 0,
                "added_on": int(b.get("time_added", time.time())),
                "completion_on": completion_time if is_completed else 0
            }
            
            if is_completed:
                if tth not in FINISHED_BUNDLES_CACHE:
                    print(f"INFO: Bundle {b['name']} marcado como completado en cache.")
                    needs_save = True
                FINISHED_BUNDLES_CACHE[tth] = res_item
                
            qbit_results.append(res_item)
            
        if needs_save:
            save_hashes()
            
        # 2. Añadir bundles del cache que ya NO están en la cola
        for tth, cached_item in FINISHED_BUNDLES_CACHE.items():
            if tth not in reported_tths:
                if req_cat and cached_item.get("category") != req_cat:
                    continue
                qbit_results.append(cached_item)
        
        if qbit_results:
            print(f"DEBUG qbit_info: Retornando {len(qbit_results)} torrents (filtro cat={req_cat}).")
        return qbit_results
    except Exception as e:
        print(f"Error en qbit_info: {e}")
        import traceback
        traceback.print_exc()
        return []

@app.post("/api/v2/torrents/add")
async def qbit_add(request: Request):
    headers = get_auth_headers()
    form_data = await request.form()
    
    with GLOBAL_SEARCH_LOCK:
        print(f"--- NUEVA SOLICITUD DE DESCARGA (qbit_add) ---")
    print(f"Headers: {dict(request.headers)}")
    print(f"Form keys: {list(form_data.keys())}")
    
    urls = form_data.get("urls", "")
    # También revisamos si viene como archivo (por si Radarr lo intentó descargar)
    torrents = form_data.get("torrents", None)
    
    if torrents:
        print("AVISO: Se ha recibido un archivo 'torrents' en lugar de URLs.")

    url_list = []
    if urls:
        url_list = urls.split("\n") if isinstance(urls, str) else [urls]
    
    if not url_list:
        print("ERROR: No se han encontrado URLs en la petición.")
    
    for url in url_list:
        url = url.strip()
        if not url: continue
        
        raw_hash = None
        if "tiger:" in url:
            raw_hash = url.split("tiger:")[1].split("&")[0]
        elif "btih:" in url:
            raw_hash = url.split("btih:")[1].split("&")[0]
            
        if raw_hash:
            tth = HASH_MAP_HEX_TO_TTH.get(raw_hash, raw_hash)
            
            # BLOQUEO DE TTH VACÍO (pero permitir sintéticos)
            if not tth or tth == "da39a3ee5e6b4b0d3255bfef95601890afd80709":
                print(f"  - ERROR CRÍTICO: El hash recibido ({raw_hash}) corresponde a un TTH vacío. No se puede descargar.")
                continue

            instance_id = None
            
            try:
                name = "Unknown"
                if "dn=" in url:
                    name = url.split("dn=")[1].split("&")[0]
                
                print(f"> Procesando descarga robusta para: {name} (TTH: {tth})")
                
                # 1. Crear instancia de búsqueda
                res = requests.post(f"{AIRDCPP_URL}/api/v1/search", json={}, headers=headers, timeout=10)
                res.raise_for_status()
                instance_id = res.json()["id"]
                
                # 2. LANZAR BÚSQUEDA
                if tth.startswith("SYNTH:"):
                    # Si es sintético, buscamos por NOMBRE SIMPLIFICADO (fallback)
                    parts = tth.split("SYNTH:")[1].rsplit(":", 1)
                    full_name = parts[0]
                    target_size_int = int(parts[1])
                    
                    search_pattern = clean_search_pattern(full_name)
                    print(f"  - Usando fallback de búsqueda (Patrón: '{search_pattern}', Original: '{full_name}')")
                    
                    search_payload = {
                        "query": {
                            "pattern": search_pattern
                        },
                        "hub_urls": []
                    }
                else:
                    # Búsqueda normal por TTH
                    search_payload = {
                        "query": {
                            "pattern": tth
                        },
                        "hub_urls": []
                    }
                
                requests.post(f"{AIRDCPP_URL}/api/v1/search/{instance_id}/hub_search", json=search_payload, headers=headers, timeout=10)
                
                # 3. Polling robusto de resultados (esperar a que se estabilice el conteo)
                print(f"  - Esperando resultados...")
                results = []
                last_count = -1
                for i in range(15):
                    time.sleep(1)
                    # Si es sintético, pedimos más para filtrar el mejor match manual
                    max_results_to_fetch = 2000 if tth.startswith("SYNTH:") else 1
                    try:
                        results_res = requests.get(f"{AIRDCPP_URL}/api/v1/search/{instance_id}/results/0/{max_results_to_fetch}", headers=headers, timeout=5)
                        if results_res.status_code == 200:
                            current_results = results_res.json()
                            current_count = len(current_results)
                            results = current_results
                            
                            # Salida temprana si el conteo se estabiliza (al menos 6 ciclos)
                            if current_count > 0 and i > 6:
                                if current_count == last_count:
                                    break
                                
                            last_count = current_count
                    except:
                        continue
                
                selected_result = None
                if results:
                    if tth.startswith("SYNTH:"):
                        # Filtrar el mejor match para el sintético
                        parts = tth.split("SYNTH:")[1].rsplit(":", 1)
                        target_name = parts[0]
                        target_size_int = int(parts[1])
                        
                        print(f"  - Analizando {len(results)} resultados de búsqueda para match con Size: {target_size_int}...")
                        for r in results:
                            r_size_raw = r.get("size", 0)
                            r_size_int = int(float(r_size_raw))
                            r_name = r.get("name")
                            
                            # Obtener tipo para filtrar
                            r_type_raw = r.get("type", "file")
                            r_type = r_type_raw.get("id", "file") if isinstance(r_type_raw, dict) else str(r_type_raw)
                            
                            # Ignorar archivos pequeños (solo carpetas o bundles grandes)
                            if r_type not in ["directory", "bundle"] and r_size_int < 1024*1024*1024:
                                continue

                            # Intentar match por tamaño exacto (lo más fiable)
                            if r_size_int == target_size_int:
                                print(f"  - Match encontrado por tamaño exacto! ({r_name})")
                                selected_result = r
                                break
                            
                            # Fallback: coincidencia cercana (1MB) y nombre parecido
                            if r_size_int > 0 and abs(r_size_int - target_size_int) < 1024 * 1024:
                                if target_name[:10].lower() in r_name.lower():
                                    print(f"  - Match cercano encontrado (dif: {abs(r_size_int - target_size_int)} bytes)")
                                    selected_result = r
                                    break
                    else:
                        selected_result = results[0]

                if selected_result:
                    result_id = selected_result["id"]
                    print(f"  - Resultado encontrado ({result_id}: {selected_result['name']}). Iniciando descarga...")
                    
                    # 5. Ejecutar descarga
                    dl_res = requests.post(
                        f"{AIRDCPP_URL}/api/v1/search/{instance_id}/results/{result_id}/download", 
                        json={"priority": 3}, 
                        headers=headers, 
                        timeout=10
                    )
                    print(f"  - AirDC++ API Result ({dl_res.status_code}): {dl_res.text}")
                    
                    if dl_res.status_code < 300:
                        dl_data = dl_res.json()
                        if "bundle_info" in dl_data:
                            new_bundle_id = str(dl_data["bundle_info"]["id"])
                            cat = form_data.get("category", "radarr")
                            
                            # Registrar categoría si es nueva
                            if cat not in KNOWN_CATEGORIES:
                                KNOWN_CATEGORIES.append(cat)
                                
                            BUNDLE_MAP_ID_TO_TTH[new_bundle_id] = tth
                            BUNDLE_MAP_ID_TO_CAT[new_bundle_id] = cat
                            save_hashes()
                            print(f"  - Mapeo guardado: Bundle {new_bundle_id} -> TTH {tth} (Cat: {cat})")
                else:
                    print(f"  - ERROR: No se encontraron fuentes adecuadas en los hubs para el TTH {tth} tras la búsqueda de fallback.")
                    
            except Exception as e:
                print(f"  - ERROR procesando {tth}: {e}")
            finally:
                if instance_id:
                    # 6. Limpiar siempre
                    try:
                        requests.delete(f"{AIRDCPP_URL}/api/v1/search/{instance_id}", headers=headers, timeout=5)
                    except:
                        pass
    
    return Response(content="Ok.", status_code=200, media_type="text/plain")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
