# Propuesta futura: RSS sintético para Radarr y Sonarr

> Estado: aparcado, no implementado. Este documento conserva la investigación y el diseño para retomarlos en el futuro.

## Conclusión de la investigación

AirDC++ no ofrece un historial global y cronológico de archivos añadidos al hub:

- `hasher_file_hashed` solo informa de archivos locales procesados por nuestro propio AirDC++ y es un evento en tiempo real, no un historial de otros usuarios.
- El protocolo ADC comunica el tamaño y número total de archivos compartidos por cada usuario, pero los nombres, rutas y TTH solo llegan como respuesta a búsquedas o al descargar listas de archivos.
- Detectar cambios de tamaño y comparar las listas completas de todos los usuarios sería costoso, incompleto y poco apropiado para una función pública.
- Radarr y Sonarr consultan el RSS Torznab sin título y esperan una lista reciente con categorías y paginación. Actualmente el bridge no dispone de una fuente global equivalente.

Referencias:

- [Eventos de hash de AirDC++ Web API](https://github.com/airdcpp/airdcpp-webapi/blob/master/api/HashApi.cpp)
- [Especificación del protocolo ADC](https://adc.sourceforge.io/ADC.html)
- [Generación de consultas recientes de Radarr](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/Indexers/Newznab/NewznabRequestGenerator.cs)

## Solución propuesta

Crear un RSS sintético y opcional basado en búsquedas dirigidas:

1. El bridge consulta en modo de solo lectura las API de las instancias Radarr y Sonarr configuradas.
2. Obtiene películas y episodios monitorizados que estén ausentes o no hayan alcanzado el cutoff.
3. Agrupa los episodios de Sonarr por serie y temporada para evitar miles de búsquedas individuales.
4. Deduplica los mismos objetivos presentes en instancias 1080p y 4K.
5. Busca un objetivo cada cierto tiempo en AirDC++.
6. Registra en SQLite cuándo observa cada TTH por primera vez.
7. Las consultas RSS de Arr reciben únicamente TTH nuevos descubiertos después de crear la referencia inicial.
8. Radarr y Sonarr aplican normalmente sus perfiles de calidad, idioma y formatos y deciden si deben descargar el resultado.

Las API keys de Arr no tienen permisos granulares. Aunque el bridge usaría exclusivamente peticiones `GET`, deben almacenarse y protegerse como secretos completos.

## Configuración pública prevista

La función permanecería desactivada por defecto para no cambiar el comportamiento de instalaciones existentes:

```env
RSS_ENABLED=false
ARR_INSTANCES_JSON=[{"name":"radarr","type":"radarr","url":"http://radarr:7878","api_key":"..."},{"name":"sonarr","type":"sonarr","url":"http://sonarr:8989","api_key":"..."}]
RSS_INCLUDE_CUTOFF_UNMET=true
RSS_ARR_SYNC_INTERVAL=900
RSS_SEARCH_INTERVAL=300
RSS_RETENTION_DAYS=30
```

- `RSS_INCLUDE_CUTOFF_UNMET=false` permitiría vigilar únicamente contenido ausente.
- `RSS_ARR_SYNC_INTERVAL=900` actualizaría la lista pendiente cada 15 minutos.
- `RSS_SEARCH_INTERVAL=300` permitiría una búsqueda dirigida cada 5 minutos.
- `RSS_RETENTION_DAYS=30` conservaría novedades suficientes para que Arr pueda recuperar páginas tras una interrupción.
- `RSS_ENABLED=true` requeriría al menos una instancia Arr válida.

## Persistencia y planificación

Añadir a SQLite:

- objetivos RSS activos, tipo y motivo —ausente o cutoff—;
- identificadores TMDB/TVDB, temporada y títulos;
- última y próxima comprobación;
- relación entre objetivo y resultado;
- `first_seen_at`, `last_seen_at` y estado de referencia o publicable;
- estado de la última sincronización de cada instancia.

Comportamiento del trabajador:

- Ejecutar una sola tarea RSS simultánea.
- No comenzar una tarea de fondo mientras AirDC++ esté atendiendo una búsqueda normal.
- Priorizar ausentes y episodios recientes, reservando también capacidad para mejoras antiguas.
- Aplicar backoff entre 15 minutos y 6 horas ante errores.
- Mantener los objetivos existentes si una instancia Arr deja de responder; solo reconciliarlos tras una sincronización correcta.
- Conservar referencias de objetivos retirados por si vuelven a ser monitorizados.

Con las cuatro instancias analizadas durante el diseño había aproximadamente 142 objetivos de Radarr y 105 combinaciones serie-temporada de Sonarr antes de deduplicar coincidencias entre 1080p y 4K. A una tarea cada cinco minutos, una vuelta completa de 247 objetivos tardaría unas 20 horas y 35 minutos; la deduplicación reduciría ese tiempo.

## Comportamiento Torznab

Cuando llegue una petición sin `q`:

- devolver novedades de películas o series según `t` y las categorías;
- ordenar por `first_seen_at` descendente;
- respetar `offset` y `limit` e incluir el total;
- usar un GUID estable basado en el identificador de release;
- usar `first_seen_at` como `pubDate` del RSS, sin cambiar la fecha real mostrada en búsquedas normales;
- mantener el resultado inofensivo de validación únicamente cuando no haya novedades, para permitir guardar el indexador.

El primer análisis de cada objetivo debe crear una referencia silenciosa: los resultados que ya existan se guardarán, pero no se publicarán. Solo los TTH desconocidos en análisis posteriores serán novedades. Esto evita que activar la función provoque descargas masivas de contenido antiguo.

Se añadiría un endpoint protegido `GET /rss/status?apikey=...` con:

- estado de las instancias Arr;
- cantidad de objetivos activos por tipo y motivo;
- última sincronización;
- última y próxima búsqueda;
- número de novedades retenidas;
- errores sanitizados, sin URLs sensibles ni claves.

## Pruebas necesarias

- Sincronización paginada de Radarr y Sonarr.
- Varias instancias, objetivos repetidos y fallos parciales.
- Agrupación de episodios por serie-temporada.
- Alternancia entre ausentes y mejoras sin inanición.
- Primer ciclo de referencia sin publicaciones.
- Publicación única de un TTH nuevo y persistencia tras reiniciar.
- Retención, orden, categorías, `offset`, `limit` y total del RSS.
- Modo `RSS_INCLUDE_CUTOFF_UNMET=false`.
- Errores y backoff sin bloquear búsquedas interactivas.
- Migración de SQLite y cancelación limpia del trabajador.
- Ausencia de API keys en logs, errores y diagnósticos.
- Validación real con las cuatro instancias actuales antes de habilitar publicaciones automáticas.

## Límites aceptados

- No es un RSS global real del hub, sino detección dirigida de novedades relevantes para las bibliotecas configuradas.
- La detección no será instantánea y dependerá del tamaño de la cola y de la respuesta del hub.
- No se descargarán ni compararán listas completas de usuarios.
- No se utilizarán eventos locales de hashing como si representasen contenido remoto.
- El bridge no ordenará descargas mediante las API de Arr; las decisiones seguirán entrando por Torznab y por el cliente qBittorrent compatible.
- Las búsquedas Torznab actuales continuarán funcionando aunque el RSS sintético no esté configurado.
