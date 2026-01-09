import unicodedata
import re

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
    if not text: return ""
    
    # 1. Quitar contenido entre corchetes y paréntesis (tags, años, etc)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    
    # 2. Reemplazar puntuación y caracteres especiales por espacios
    # Incluimos coma, dos puntos, punto y coma, exclamación, interrogación, etc.
    for char in ".,:;!?_-()[]":
        text = text.replace(char, " ")
    
    # 3. Quitar indicadores de temporada (problemáticos para búsqueda literal)
    text = re.sub(r'\b(Temporada|Season|Staffel|Temp|Part|Pt|S|T)\s*\d+\b', '', text, flags=re.IGNORECASE)
    
    # 4. Quitar tags comunes de release
    text = re.sub(r'\b(NF|WEB-DL|HMAX|DSNP|AMZN|AVC|DD\+|Atmos|HDO|1080p|720p|x264|x265|HEVC|Dual|PACK|REMASTERED|EXTENDED|REPACK|UNRATED|BLURAY|BDRIP|BRRIP)\b', '', text, flags=re.IGNORECASE)
    
    # 5. Quedarse con las primeras 5 palabras (título base)
    # Master usaba 4, Dev usaba 7. 5 es un buen punto medio para evitar excesiva basura.
    words = text.split()
    clean = " ".join(words[:5]).strip()
    
    # Si la limpieza ha borrado TODO, devolvemos las primeras palabras del original
    if not clean and words:
        return " ".join(words[:3]) or text
        
    return clean
