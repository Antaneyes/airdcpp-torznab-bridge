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

def clean_search_pattern(text, max_words=None):
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
    
    # 4. Limpieza final de espacios extra y truncado opcional
    words = text.split()
    if max_words:
        words = words[:max_words]
    
    clean = " ".join(words).strip()
    
    # Si la limpieza ha borrado TODO (poco probable), devolvemos el original
    if not clean:
        return text
        
    return clean
