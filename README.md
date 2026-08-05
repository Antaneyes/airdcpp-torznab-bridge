# AirDC++ Torznab Bridge

Puente compatible con Torznab y con el subconjunto de la Web API de qBittorrent que usan Radarr y Sonarr. Permite
buscar contenido en los hubs de AirDC++, iniciar la descarga y seguir su estado desde Arr.

> La versión 2 está en beta. No expongas el servicio directamente a Internet.

## Características

- Búsquedas Torznab de películas, episodios y temporadas.
- Resolución opcional de títulos mediante TMDB y TVMaze, sin traducciones automáticas inventadas.
- Adaptador qBittorrent con categorías configurables; incluye `radarr`, `sonarr`, `radarr4k` y `sonarr4k` por defecto.
- Persistencia SQLite y migración automática del esquema anterior.
- Autenticación independiente para Torznab, Arr y AirDC++.
- Caché, coalescencia y límite global para no inundar los hubs con búsquedas repetidas.
- Resultado sintético claramente identificado únicamente para la consulta vacía con la que Arr valida el indexador.
- Imágenes Docker `linux/amd64` y `linux/arm64`.

## Instalación beta

```bash
cp .env.example .env
# Edita .env y usa secretos aleatorios largos.
docker compose up -d --build
curl http://localhost:8001/health/live
```

La beta usa el puerto `8001` y el volumen Docker `bridge-v2-data`, por lo que puede convivir con una instalación
anterior. Para migrar el estado, arranca la beta una vez, detenla y copia la base con:

```bash
docker compose stop
docker run --rm -v airdcpp-torznab-bridge_bridge-v2-data:/target \
  -v /ruta/a/la/base/anterior:/source:ro busybox \
  sh -c 'cp /source/bridge.db /target/bridge.db && chown 10001:10001 /target/bridge.db'
docker compose up -d
```

La migración crea automáticamente una copia `bridge.db.v0.bak-*` antes de modificar el esquema.

### Radarr y Sonarr

Indexer Torznab:

- URL: `http://host:8001/torznab`
- API key: el valor de `BRIDGE_API_KEY`
- Categoría: `2000` para Radarr y `5000` para Sonarr

Cliente qBittorrent:

- Host/puerto: `host:8001`
- Usuario/contraseña: `BRIDGE_USERNAME` y `BRIDGE_PASSWORD`
- Categoría: una de las configuradas en `DOWNLOAD_CATEGORIES` (`radarr`, `sonarr`, `radarr4k` o `sonarr4k` por defecto)

Configura el Remote Path Mapping de Arr cuando `SAVE_PATH` no coincida con la ruta visible dentro de sus
contenedores.

## Configuración principal

| Variable | Descripción | Predeterminado |
| --- | --- | --- |
| `AIRDCPP_URL` | URL de AirDC++ | `http://localhost:5600` |
| `AIRDCPP_USER` / `AIRDCPP_PASS` | Credenciales de AirDC++ | obligatorias |
| `BRIDGE_API_KEY` | Clave del indexador Torznab | obligatoria |
| `BRIDGE_USERNAME` / `BRIDGE_PASSWORD` | Login qBittorrent de Arr | obligatorias |
| `DOWNLOAD_CATEGORIES` | Categorías qBittorrent separadas por comas | `radarr,sonarr,radarr4k,sonarr4k` |
| `TMDB_API_KEY` | Enriquecimiento opcional de títulos | vacío |
| `SAVE_PATH` | Ruta que se anuncia a Arr | `/downloads` |
| `COMPLETED_RATIO` | Ratio virtual al completar | `1.5` |
| `ALLOW_FILE_DELETE` | Permite solicitar borrado al retirar | `false` |
| `AIRDCPP_MAX_ACTIVE_SEARCHES` | Búsquedas AirDC++ simultáneas | `1` |
| `SEARCH_TIMEOUT` | Espera máxima por variante | `10` segundos |
| `ALLOW_INSECURE` | Desactiva autenticación; solo para redes aisladas | `false` |

## Desarrollo

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/pytest --cov=app
```

Licencia: [GPL-3.0](LICENSE).
