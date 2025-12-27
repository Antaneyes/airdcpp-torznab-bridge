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
   - Copia el archivo `.env.example` (o crea uno nuevo) y renómbralo a `.env`.
   - Modifica los valores con tus credenciales de AirDC++:
     ```env
     AIRDCPP_URL=http://tu-ip:5600
     AIRDCPP_USER=tu-usuario
     AIRDCPP_PASS=tu-contraseña
     ```
3. **Levantar el servicio**:
   ```bash
   docker-compose up -d --build
   ```

## ⚙️ Configuración en Radarr/Sonarr

### 1. Indexador (Torznab)
- **URL**: `http://localhost:8000/torznab/api`
- **API Key**: (Cualquier valor, el puente no la valida)
- **Categorías**: 5000 (TV), 2000 (Movies).

### 2. Cliente de Descarga (qBittorrent)
- **Host**: `localhost`
- **Puerto**: `8000`
- **Nombre de usuario/Contraseña**: (Los mismos que en `.env`)
- **Categoría**: `sonarr` o `radarr` (Fundamental para el aislamiento).

## 📁 Estructura del Proyecto

- `bridge.py`: El núcleo de la aplicación (FastAPI).
- `docker-compose.yml`: Configuración del contenedor.
- `.env`: Configuración sensible (no subir al control de versiones).
- `bridge_hashes.json`: Base de datos local de persistencia para mapear descargas.
