# Actualizar desde v1 a v2

La versión 2 sustituye el JSON de v1 por SQLite y activa autenticación obligatoria. Haz una copia del directorio `data` antes de comenzar.

## Cambios que requieren atención

| v1 | v2 |
| --- | --- |
| `bridge_hashes.json` | `bridge.db`, con importación automática del JSON |
| Torznab sin autenticación | `BRIDGE_API_KEY` obligatoria |
| Autenticación de descarga inconsistente | `BRIDGE_USERNAME` y `BRIDGE_PASSWORD` obligatorios |
| Clave TMDB incrustada | `TMDB_API_KEY` propia y opcional |
| `AIRDCPP_CATEGORIES` | `DOWNLOAD_CATEGORIES` |
| Ruta `/downloads` prácticamente fija | `SAVE_PATH` y Remote Path Mapping explícitos |
| Puerto `8000` | El ejemplo beta usa `8001`; internamente sigue siendo `8000` |

Si utilizabas la categoría `airdcpp`, inclúyela: `DOWNLOAD_CATEGORIES=airdcpp,radarr,sonarr`.

## Opción recomendada: actualización paralela

1. Copia `data`: `cp -a data data.backup-v1`.
2. Arranca v2 en el puerto `8001` con un volumen nuevo y configura los secretos.
3. Prueba `/health/ready` y añade temporalmente el indexador y cliente v2 a una instancia Arr.
4. Mantén v1 hasta terminar o importar sus descargas activas.
5. Tras validar v2, desactiva las entradas v1 y retira el contenedor antiguo.

El modo paralelo no transfiere la cola antigua porque ambos bridges no deben administrar simultáneamente los mismos bundles.

## Sustitución directa conservando el estado

1. Detén v1 y crea la copia:

   ```bash
   docker compose down
   cp -a data data.backup-v1
   ```

2. Usa la imagen v2 pero conserva el montaje `./data:/app/data`. Puedes mantener `8000:8000` para no cambiar la dirección en Arr.
3. Añade las nuevas variables de `.env.example` y configura `PUBLIC_URL`.
4. Arranca v2. Copiará el JSON como `bridge_hashes.json.v1.bak`, importará sus hashes, bundles, categorías y finalizados a `bridge.db`, y dejará el original intacto.
5. Actualiza la API key de Torznab y el usuario/contraseña qBittorrent en Arr. Revisa también Remote Path Mapping si cambió el host, puerto o `SAVE_PATH`.
6. Comprueba `/health/ready`, prueba ambas conexiones y revisa la cola antes de habilitar búsquedas automáticas.

La importación es idempotente y no duplica datos al reiniciar.

## Usar el volumen nombrado nuevo

Antes del primer arranque copia `bridge_hashes.json` desde el antiguo `./data`:

```bash
docker compose create
docker run --rm \
  -v "$(pwd)/data:/source:ro" \
  -v airdcpp-torznab-bridge_bridge-data:/target \
  busybox cp /source/bridge_hashes.json /target/bridge_hashes.json
docker compose up -d
```

Comprueba el nombre real del volumen con `docker volume ls`, ya que incluye el nombre del proyecto Compose.

## Volver a v1

1. Detén v2.
2. Recupera el Compose antiguo desde `legacy-v1`.
3. Restaura `data.backup-v1` si v1 modificó su estado después de la copia.
4. Vuelve a activar las entradas antiguas en Arr.

No ejecutes v1 y una v2 migrada sobre el mismo directorio de datos al mismo tiempo.
