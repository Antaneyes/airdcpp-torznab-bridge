import requests
import re
from app.config import TMDB_API_KEY
from app.core.logging import get_logger

logger = get_logger("app.metadata")
logger.info(f"Configuración de metadatos cargada. TMDB_API_KEY detectada: {'SÍ' if TMDB_API_KEY else 'NO'}")

TITLE_CACHE = {} # Mapeo de ID -> [Nombres]

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
            logger.debug(f"TMDB encontró nombres para {key}: {titles}")
            
    # 2. Usar TVMaze para obtener más alias o si TMDB falló
    try:
        url = ""
        if imdbid:
            url = f"https://api.tvmaze.com/lookup/shows?imdb={imdbid}"
        elif tvdbid:
            url = f"https://api.tvmaze.com/lookup/shows?thetvdb={tvdbid}"
            
        if url:
            logger.debug(f"Consultando TVMaze para ID: {key} (Complemento)")
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                tvmaze_titles = extract_titles_from_tvmaze_show(data)
                # Añadir los que no tengamos ya
                for t in tvmaze_titles:
                    if t not in titles:
                        titles.append(t)
            elif r.status_code == 404 and (imdbid or tvdbid):
                logger.debug(f"ID {key} no encontrado en TVMaze.")
    except Exception as e:
        logger.error(f"Error resolviendo títulos por ID en TVMaze: {e}")
        
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
                if a.get("iso_3166_1") == "ES":
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
            
            logger.info(f"TMDB resolvió para '{query or tmdbid or imdbid}' (Filtrado Español): {titles}")
    except Exception as e:
        logger.error(f"Error en TMDB: {e}")
        
    return titles

def resolve_titles_by_name(query):
    """Intenta encontrar una serie/peli por nombre y sacar sus AKAs."""
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
        logger.debug(f"Buscando en TVMaze por nombre: '{clean_q}'")
        url = f"https://api.tvmaze.com/singlesearch/shows?q={clean_q}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            titles = extract_titles_from_tvmaze_show(data)
    except Exception as e:
        logger.error(f"Error resolviendo títulos por nombre: {e}")

    if titles:
        logger.info(f"Títulos encontrados por nombre para '{clean_q}': {titles}")
        TITLE_CACHE[clean_q] = titles
    
    is_series_match = titles and ":" in titles[0] and ":" not in clean_q
    
    if not titles or is_series_match:
        guess = translate_title_to_spanish(clean_q)
        if guess and guess.lower() != clean_q.lower():
            if guess not in titles:
                logger.debug(f"Agregando adivinanza en español: '{guess}'")
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
                    
                    if (ak.get("country") or {}).get("code") == "ES":
                        if name not in spanish_titles:
                            spanish_titles.append(name)
                    elif not ak.get("country"): # Alias general
                        if name not in other_titles and name not in spanish_titles:
                            other_titles.append(name)
    except Exception as e:
        logger.error(f"Error extrayendo títulos: {e}")
    
    return spanish_titles + [t for t in other_titles if t not in spanish_titles]
