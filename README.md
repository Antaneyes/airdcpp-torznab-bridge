# AirDC++ Bridge para Radarr y Sonarr

Este proyecto actúa como un puente (bridge) entre **AirDC++** y las aplicaciones de la familia *Arr (Radarr y Sonarr), emulando los APIs de qBittorrent (para descargas) y Torznab (para búsquedas).

## 🚀 Características Principales

- **Resolución de Títulos Avanzada**: Utiliza **TMDB** (TheMovieDB) y TVMaze para obtener nombres en español y alias exactos.
- **Normalización de Acentos**: Genera automáticamente variantes con y sin acentos para máxima compatibilidad con hubs.
- **Búsqueda con Año**: Detecta e incluye el año de lanzamiento en las búsquedas de películas para filtrar el ruido.
- **Soporte de Temporadas Exhaustivo**: Búsqueda multi-variante y renombrado automático de carpetas genéricas (ej: "Temporada 1" -> "Show - Temporada 1").
- **Seguimiento en Tiempo Real**: API de qBittorrent optimizada para una importación casi instantánea en Radarr/Sonarr tras finalizar la descarga en AirDC++.
- **Seguridad**: Configuración sensible centralizada en un archivo `.env`.

## 🛠️ Instalación y Uso

1. **Requisitos**: Tener Docker y Docker Compose instalados.
2. **Configuración**:
   - Descarga o crea un archivo `docker-compose.yml` (puedes copiar el contenido de este repositorio).
   - Crea un archivo `.env` en la misma carpeta basándote en el `.env.example`.
   - Modifica los valores con tus credenciales de AirDC++.
3. **Levantar el servicio**:
   ```bash
   docker compose up -d
   ```
    *Esto descargará automáticamente la última imagen oficial desde GitHub Container Registry o Docker Hub.*

## ⚙️ Configuración en Radarr/Sonarr

### 1. Indexador (Torznab)
- **URL**: `http://tu-ip:8000/torznab`
- **API Key**: (Cualquier valor, el puente no la valida)
- **Categorías**: 5000 (TV), 2000 (Movies).
- **Búsqueda Automática**: Puede activarse con seguridad; el bridge gestiona internamente la concurrencia para evitar bloqueos en los hubs.

### 2. Cliente de Descarga (qBittorrent)
- **Host**: `tu-ip`
- **Puerto**: `8000`
- **Username/Password**: Los mismos configurados en el `.env`.
- **Categoría**: `radarr` o `sonarr` (deben coincidir con las configuradas en `AIRDCPP_CATEGORIES`).

### 3. Mapeo de Rutas (Remote Path Mapping)
Si el contenedor de Radarr/Sonarr no ve la misma ruta que AirDC++, configura un *Remote Path Mapping* en `Settings > Download Clients`:
- **Host**: `tu-ip`
- **Remote Path**: La ruta que reporta AirDC++ (ej: `/downloads/`).
- **Local Path**: La ruta donde Radarr/Sonarr ve esos archivos (ej: `/data/downloads/`).

## 📁 Estructura del Proyecto

- `bridge.py`: El núcleo de la aplicación (FastAPI).
- `docker-compose.yml`: Configuración del contenedor.
- `.env`: Configuración sensible (no subir al control de versiones).
- `data/bridge_hashes.json`: Base de datos local de persistencia (creada automáticamente).
