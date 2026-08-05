# Actualizar desde v1 a v2

Cambiar solamente `:latest` por `:beta` **no es suficiente**. Puedes conservar la dirección, el puerto `8000`, el directorio `data` y las entradas existentes de Radarr/Sonarr, pero v2 necesita nuevas credenciales y variables.

Esta guía ofrece dos opciones:

- **Sustitución directa**, recomendada para la mayoría: conserva `http://SERVIDOR:8000` y migra los datos de v1 automáticamente.
- **Prueba paralela**, más prudente: ejecuta v2 temporalmente en `8001` sin retirar v1.

## Antes de empezar

1. Localiza la carpeta que contiene el `docker-compose.yml` de v1 y entra en ella.
2. Comprueba que `data/bridge_hashes.json` existe. Si utilizaste otro montaje, localiza el directorio conectado a `/app/data`.
3. No ejecutes v1 y v2 simultáneamente sobre el mismo directorio `data`.
4. Usa inicialmente la versión numerada `2.0.0-beta.3`, no `latest` ni la etiqueta móvil `beta`.

## Opción A: sustitución directa conservando puerto y datos

Este procedimiento mantiene la URL `http://SERVIDOR:8000`. No tendrás que cambiar el host ni el puerto en Radarr/Sonarr.

### 1. Detén v1 y crea una copia

```bash
docker compose down
cp -a data data.backup-v1
sudo chown -R 10001:10001 data
```

V2 se ejecuta sin privilegios con UID/GID `10001`. El `chown` le permite crear `bridge.db` dentro del directorio que pertenecía a v1. La copia conserva el estado anterior para poder volver atrás.

No elimines el contenedor con sus volúmenes si utilizabas un volumen Docker en lugar de `./data`. Consulta [Si v1 usaba un volumen Docker](#si-v1-usaba-un-volumen-docker).

### 2. Crea el archivo `.env`

Copia `.env.example` de v2 como `.env` y edita, como mínimo, estos valores:

```env
BRIDGE_IMAGE_TAG=2.0.0-beta.3
BRIDGE_PORT=8000

AIRDCPP_URL=http://host.docker.internal:5600
AIRDCPP_USER=TU_USUARIO_AIRDCPP
AIRDCPP_PASS=TU_CONTRASEÑA_AIRDCPP
AIRDCPP_WEB_URL=http://IP_DEL_SERVIDOR:5600

PUBLIC_URL=http://IP_DEL_SERVIDOR:8000
BRIDGE_API_KEY=GENERA_UNA_CLAVE_LARGA_Y_ALEATORIA
BRIDGE_USERNAME=arr
BRIDGE_PASSWORD=GENERA_OTRA_CONTRASEÑA_LARGA

SAVE_PATH=/downloads
DOWNLOAD_CATEGORIES=airdcpp,radarr,sonarr
ALLOW_INSECURE=false
```

Notas:

- `PUBLIC_URL` debe ser una URL que Radarr y Sonarr puedan alcanzar. No uses `localhost` salvo que Arr esté en el mismo contenedor.
- Si antes utilizabas la categoría `airdcpp`, mantenla en `DOWNLOAD_CATEGORIES`.
- Añade `radarr4k` o `sonarr4k` si también usas esas categorías.
- `TMDB_API_KEY` es opcional, pero mejora la obtención de títulos alternativos.
- Si no tienes HTTPS, `ALLOW_INSECURE=false` sigue siendo válido en una red local. Ese valor mantiene obligatorias las credenciales; no obliga a usar HTTPS.

### 3. Sustituye el Compose de v1

Para conservar el directorio `./data` y el puerto anterior, usa:

```yaml
services:
  airdcpp-bridge:
    image: ghcr.io/antaneyes/airdcpp-torznab-bridge:${BRIDGE_IMAGE_TAG:-2.0.0-beta.3}
    container_name: airdcpp-bridge
    ports:
      - "${BRIDGE_PORT:-8000}:8000"
    env_file:
      - .env
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./data:/app/data
    read_only: true
    tmpfs:
      - /tmp:size=16m,mode=1777
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    restart: unless-stopped
```

Si AirDC++, Radarr o Sonarr se comunican por redes Docker, vuelve a añadir al servicio las mismas redes externas que utilizabas antes.

### 4. Arranca v2 y comprueba la migración

```bash
docker compose pull
docker compose up -d
docker compose logs --tail=100 airdcpp-bridge
curl http://localhost:8000/health/ready
```

La última orden debe devolver:

```json
{"status":"ready"}
```

En el primer arranque, v2:

1. copia `bridge_hashes.json` como `bridge_hashes.json.v1.bak`;
2. importa hashes, bundles, categorías y finalizados en `bridge.db`;
3. conserva intacto el JSON original.

La importación es idempotente: reiniciar v2 no duplica los registros.

### 5. Actualiza Radarr y Sonarr

No cambies host ni puerto si conservaste `airdcpp-bridge:8000` dentro de Docker o `IP_DEL_SERVIDOR:8000` fuera de Docker.

En cada **indexador Torznab**:

- URL: conserva la anterior.
- API Path: `/api` si la aplicación lo solicita.
- API Key: introduce el valor de `BRIDGE_API_KEY`.
- Pulsa **Test** y guarda.

En cada **cliente de descarga qBittorrent** que apunta al bridge:

- Host y puerto: conserva los anteriores.
- Usuario: el valor de `BRIDGE_USERNAME`.
- Contraseña: el valor de `BRIDGE_PASSWORD`.
- Categoría: debe figurar en `DOWNLOAD_CATEGORIES`.
- Pulsa **Test** y guarda.

Si `SAVE_PATH`, el host o el puerto han cambiado, revisa también **Remote Path Mapping**. Si no han cambiado, no lo modifiques.

### 6. Validación final

Antes de reactivar búsquedas automáticas:

1. prueba el indexador en Radarr/Sonarr;
2. prueba el cliente de descarga;
3. realiza una búsqueda interactiva;
4. descarga un resultado pequeño o conocido;
5. confirma que aparece en la cola y que AirDC++ recibe el bundle correcto.

## Opción B: probar v2 en paralelo

Usa esta opción si quieres validar v2 antes de retirar v1.

1. Mantén v1 en `8000`.
2. Copia `data` a otro directorio: `cp -a data data-v2`.
3. Configura v2 con `BRIDGE_PORT=8001`, `PUBLIC_URL=http://IP_DEL_SERVIDOR:8001` y `./data-v2:/app/data`.
4. Usa otro nombre de contenedor, por ejemplo `airdcpp-bridge-v2`.
5. Añade temporalmente el indexador y cliente v2 a una sola instancia Arr.
6. Desactiva las búsquedas automáticas durante la prueba y no envíes el mismo resultado a ambos bridges.
7. Cuando termines, detén v1, conserva v2 y cambia a `8000` si quieres recuperar la URL anterior.

Las colas que cambien después de copiar `data` no se sincronizan entre ambos bridges. Finaliza o revisa las descargas activas antes del cambio definitivo.

## Si v1 usaba un volumen Docker

Identifica primero el volumen conectado a `/app/data`:

```bash
docker inspect airdcpp-bridge --format '{{range .Mounts}}{{println .Name .Source .Destination}}{{end}}'
```

La opción más sencilla es reutilizar ese mismo volumen en el Compose de v2:

```yaml
volumes:
  - NOMBRE_REAL_DEL_VOLUMEN:/app/data

volumes:
  NOMBRE_REAL_DEL_VOLUMEN:
    external: true
```

Haz una copia antes de arrancar v2. No declares un volumen nuevo vacío esperando que Docker copie automáticamente `bridge_hashes.json`.

Con v1 detenido, concede acceso al usuario sin privilegios de v2:

```bash
docker run --rm \
  -v NOMBRE_REAL_DEL_VOLUMEN:/data \
  alpine chown -R 10001:10001 /data
```

Este comando cambia los propietarios, por lo que debes ejecutarlo únicamente después de tener una copia del volumen.

## Volver a v1

Si alguna comprobación falla:

```bash
docker compose down
mv data data.failed-v2
cp -a data.backup-v1 data
```

Después recupera el Compose anterior desde la rama [`legacy-v1`](https://github.com/Antaneyes/airdcpp-torznab-bridge/tree/legacy-v1), arráncalo y vuelve a activar las entradas antiguas de Arr.

No borres `data.failed-v2` hasta entender el fallo. Si usas volúmenes Docker, restaura la copia del volumen con el método que utilices para tus copias de seguridad.

## Resumen de cambios de configuración

| v1 | v2 |
| --- | --- |
| `bridge_hashes.json` | `bridge.db`, con importación automática |
| Torznab sin API key | `BRIDGE_API_KEY` obligatoria |
| Autenticación de descarga inconsistente | `BRIDGE_USERNAME` y `BRIDGE_PASSWORD` obligatorios |
| Clave TMDB incrustada | `TMDB_API_KEY` propia y opcional |
| `AIRDCPP_CATEGORIES` | `DOWNLOAD_CATEGORIES` |
| Ruta prácticamente fija | `SAVE_PATH` explícito |
| Puerto externo `8000` | Puede seguir siendo `8000`; el ejemplo de instalación nueva usa `8001` |
