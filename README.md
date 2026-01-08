# AirDC++ Bridge para Radarr y Sonarr

Este proyecto actúa como un puente (bridge) entre **AirDC++** y las aplicaciones de la familia *Arr (Radarr y Sonarr), emulando los APIs de qBittorrent (para descargas) y Torznab (para búsquedas).

## 🚀 Características Principales

- **Resolución de Títulos Avanzada**: Utiliza **TMDB** (TheMovieDB) y TVMaze para obtener nombres en español y alias exactos.
- **Normalización de Acentos**: Genera automáticamente variantes con y sin acentos para máxima compatibilidad con hubs.
- **Búsqueda Robusta**: Realiza búsquedas por nombre exacto y verifica el TTH para asegurar que descargas lo que elegiste.
- **Persistencia en SQLite**: Migración de JSON a una base de datos SQLite más robusta y eficiente.
- **Caché de XML**: Respuestas casi instantáneas para búsquedas repetitivas de Radarr/Sonarr.
- **Seguimiento en Tiempo Real**: API de qBittorrent optimizada para una importación instantánea y visibilidad completa de la cola.
- **Borrado Sincronizado**: Al borrar una descarga en Radarr/Sonarr, se elimina automáticamente del cliente AirDC++.

## 🛠️ Instalación y Uso

La forma más sencilla de ejecutar el bridge es mediante **Docker Compose**.

### 1. Preparar la Configuración
- Crea un archivo `.env` basado en el `.env.example`.
- **Importante**: Añade tu `TMDB_API_KEY` para que el bridge pueda encontrar los nombres de las películas en español.

### 2. Archivo `docker-compose.yml`
Crea un archivo llamado `docker-compose.yml` (o `compose.yaml`) con el siguiente contenido:

```yaml
version: '3.8'

services:
  airdcpp-bridge:
    # OPCIÓN A: Versión Estable (Recomendada)
    image: ghcr.io/antaneyes/airdcpp-torznab-bridge:latest
    
    # OPCIÓN B: Versión de Desarrollo (Novedades)
    # image: ghcr.io/antaneyes/airdcpp-torznab-bridge:dev

    # OPCIÓN C: Desarrollo Local (Construir desde el código)
    # build: . 
    
    container_name: airdcpp-bridge
    ports:
      - 8000:8000
    environment:
      - AIRDCPP_URL=${AIRDCPP_URL}
      - AIRDCPP_USER=${AIRDCPP_USER}
      - AIRDCPP_PASS=${AIRDCPP_PASS}
      - TMDB_API_KEY=${TMDB_API_KEY}
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./data:/app/data
    restart: always
```

### 3. Levantar el servicio
```bash
docker compose up -d
```

> [!TIP]
> Si quieres probar las últimas funciones antes de que salgan a la versión principal, cambia la etiqueta de la imagen de `:latest` a `:dev` y ejecuta `docker compose pull && docker compose up -d`.

## ⚙️ Configuración en Radarr/Sonarr

### 1. Indexador (Torznab)
- **URL**: `http://tu-ip:8000/torznab`
- **API Key**: (Cualquier valor)
- **Categorías**: 5000 (TV), 2000 (Movies).

### 2. Cliente de Descarga (qBittorrent)
- **Host**: `tu-ip`
- **Puerto**: `8000`
- **Username/Password**: Los mismos configurados en el `.env`.
- **Categoría**: `radarr` o `sonarr`.

## 📁 Estructura del Proyecto

- `app/main.py`: Punto de entrada de la aplicación FastAPI.
- `app/routers/`: Definición de los endpoints (Torznab, qBittorrent, General).
- `app/services/`: Lógica de negocio (AirDC++, Base de Datos, Metadatos).
- `app/core/`: Configuración global, logging y bloqueos.
- `app/utils/`: Utilidades de texto y generación de XML.
- `data/bridge.db`: Base de datos SQLite (creada automáticamente).