from fastapi import FastAPI, Request
import time
import requests
from app.routers import general, torznab, qbittorrent
from app.services.airdcpp import AIRDCPP_URL, get_auth_headers
from app.services.persistence import load_hashes
from app.core.logging import setup_logging, get_logger

# Inicializar logging
setup_logging()
logger = get_logger("app.main")

app = FastAPI(title="AirDC++ Torznab/qBit Bridge")

@app.middleware("http")
async def session_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    path = request.url.path
    # Rutas ruidosas de Radarr/Sonarr
    noisy_paths = ["/api/v2/app/webapiVersion", "/api/v2/app/preferences", "/api/v2/torrents/info"]
    
    log_msg = f"RES: {request.method} {path} - Status: {response.status_code} - Tiempo: {duration:.2f}s"
    
    # Lógica de niveles:
    # 1. Si es un error, siempre INFO
    if response.status_code >= 400:
        logger.info(log_msg)
    # 2. Si es una ruta ruidosa y fue rápida, a DEBUG (oculto)
    elif any(noisy in path for noisy in noisy_paths) and duration < 0.5:
        logger.debug(log_msg)
    # 3. Si es una búsqueda de torznab muy rápida (caché), a DEBUG (oculto)
    elif "/torznab" in path and duration < 0.1:
        logger.debug(log_msg)
    # 4. Todo lo demás (descargas, borrados, búsquedas reales) a INFO
    else:
        logger.info(log_msg)
    
    return response

@app.on_event("startup")
def startup_event():
    logger.info("--- Iniciando AirDC++ Bridge ---")
    load_hashes() # Asegurar que la base de datos se inicializa y loguea la ruta
    
    logger.info("--- Test de Conectividad AirDC++ ---")
    try:
        r = requests.get(f"{AIRDCPP_URL}/api/v1/hubs", headers=get_auth_headers(), timeout=5)
        if r.status_code == 200:
            logger.info("Conexión con AirDC++ establecida correctamente.")
        else:
            logger.warning(f"AirDC++ respondió con status {r.status_code}")
    except Exception as e:
        logger.error(f"Fallo de conexión: {e}")

app.include_router(general.router)
app.include_router(torznab.router)
app.include_router(qbittorrent.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)