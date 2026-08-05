# AirDC++ Torznab Bridge v2

Puente compatible con Torznab y con el subconjunto de la API de qBittorrent utilizado por Radarr y Sonarr. Permite buscar contenido en hubs de AirDC++, iniciar descargas y seguirlas desde Arr.

> La versión 2 es una beta pública. Úsala únicamente dentro de una red de confianza y no la expongas directamente a Internet.

**[Actualización desde v1](UPGRADING.md)** · **[Registro de cambios](../../CHANGELOG.md)** · **[README internacional](../../README.md)**

## Funciones principales

- Búsquedas Torznab de películas, episodios y temporadas.
- Coincidencia estricta de título y año con alias opcionales de TMDB.
- Detección de español, inglés, dual y multi sin inventar idiomas ausentes.
- Detección de temporadas en subcarpetas y selección de una temporada cuando varias comparten carpeta.
- Fechas, tamaños y disponibilidad procedentes de AirDC++.
- Cliente compatible con qBittorrent para seguimiento e importación en Arr.
- Categorías configurables para varias instancias 1080p/4K.
- Persistencia SQLite, importación automática de v1, caché y límite de búsquedas al hub.
- Enlaces opcionales desde los resultados de Arr hasta la carpeta de AirDC++.

## Requisitos

- AirDC++ Web Client en funcionamiento y accesible desde el bridge.
- Docker Engine y Docker Compose v2.
- Radarr y/o Sonarr con acceso a la dirección del bridge.
- Una API key de TMDB es opcional, pero recomendable para títulos traducidos y alternativos.

El usuario de AirDC++ debe poder consultar hubs, buscar, abrir listas de archivos, administrar la cola e iniciar descargas.

## Instalación rápida

Descarga `docker-compose.yml` y `.env.example`:

```bash
cp .env.example .env
# Edita .env y sustituye todos los valores change-me.
docker compose up -d
docker compose ps
curl http://localhost:8001/health/ready
```

La imagen predeterminada es `ghcr.io/antaneyes/airdcpp-torznab-bridge:beta`. Para fijar la versión usa `BRIDGE_IMAGE_TAG=2.0.0-beta.2`.

Si AirDC++ está en otro contenedor de la misma red Docker, usa `AIRDCPP_URL=http://airdcpp:5600` y conecta el bridge a esa red. Si AirDC++ publica el puerto 5600 en el host, usa `http://host.docker.internal:5600` con el `extra_hosts` incluido.

## Radarr y Sonarr

Indexador **Torznab**:

- URL: `http://host-del-bridge:8001/torznab`.
- API key: el valor de `BRIDGE_API_KEY`.
- Categoría: películas/`2000` en Radarr y televisión/`5000` en Sonarr.

Cliente de descarga **qBittorrent**:

- Host y puerto: dirección del bridge y `8001`.
- Usuario y contraseña: `BRIDGE_USERNAME` y `BRIDGE_PASSWORD`.
- Categoría: `radarr` o `sonarr`; debe figurar en `DOWNLOAD_CATEGORIES`.
- Desactiva la descarga secuencial y la prioridad de primera/última pieza.

Entre contenedores de la misma red puedes usar `airdcpp-bridge:8000`. Configura `PUBLIC_URL` con una dirección que Arr pueda usar para obtener el resultado.

Si `SAVE_PATH` no coincide con la ruta visible en Arr, crea un Remote Path Mapping. El host debe coincidir exactamente con el cliente de descarga, la ruta remota será `SAVE_PATH` y la local será el montaje equivalente dentro de Arr.

## Variables importantes

- `AIRDCPP_URL`, `AIRDCPP_USER`, `AIRDCPP_PASS`: conexión con AirDC++.
- `BRIDGE_API_KEY`: autenticación Torznab y de enlaces.
- `BRIDGE_USERNAME`, `BRIDGE_PASSWORD`: autenticación del cliente qBittorrent.
- `TMDB_API_KEY`: títulos alternativos y traducidos.
- `SAVE_PATH`: ruta anunciada a Arr.
- `DOWNLOAD_CATEGORIES`: categorías aceptadas, separadas por comas.
- `PUBLIC_URL`: URL del bridge usada en enlaces de descarga.
- `AIRDCPP_WEB_URL`: activa enlaces navegables a carpetas de AirDC++.
- `ALLOW_FILE_DELETE`: permite borrar datos solo cuando Arr lo solicita expresamente; predeterminado `false`.
- `ALLOW_INSECURE`: desactiva la autenticación; úsalo solo para pruebas en redes aisladas.

Todas las variables avanzadas, sus valores predeterminados y los ajustes de caché/búsqueda aparecen en [el README principal](../../README.md#configuration) y en `.env.example`.

## Diagnóstico

- `/health/live`: comprueba el proceso del bridge.
- `/health/ready`: comprueba también la conexión con AirDC++.
- La prueba vacía de un indexador devuelve un elemento marcado como validación. No es contenido descargable.
- Una primera búsqueda puede tardar varios segundos; las repetidas suelen salir de caché.
- Consulta los logs con `docker compose logs -f --tail=200`.

Consulta [SECURITY.md](../../SECURITY.md) antes de permitir acceso fuera de tu LAN.

Para actualizar dentro del canal beta:

```bash
docker compose pull
docker compose up -d
curl http://localhost:8001/health/ready
```

Haz una copia del volumen antes de cambiar de versión beta y fija `BRIDGE_IMAGE_TAG` a una versión numerada si no quieres actualizaciones automáticas.
