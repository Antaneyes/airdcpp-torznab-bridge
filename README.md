# AirDC++ Torznab Bridge

[![CI](https://github.com/Antaneyes/airdcpp-torznab-bridge/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Antaneyes/airdcpp-torznab-bridge/actions/workflows/docker-publish.yml)
[![Release](https://img.shields.io/github/v/release/Antaneyes/airdcpp-torznab-bridge?include_prereleases)](https://github.com/Antaneyes/airdcpp-torznab-bridge/releases)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

An adapter that lets Radarr and Sonarr search AirDC++ hubs through Torznab and use AirDC++ as a qBittorrent-compatible download client.

> Version 2 is public beta software. Keep it on a trusted network and do not expose it directly to the Internet.

**[Guía completa en español](docs/es/README.md)** · **[Upgrade from v1](UPGRADING.md)** · **[Changelog](CHANGELOG.md)**

## What it does

- Movie, episode and season searches through Torznab.
- Exact title/year matching with optional TMDB aliases.
- Spanish, English, dual and multi-language hints without guessing when metadata is absent.
- Nested season detection and selective downloads when several seasons share one folder.
- Real AirDC++ dates, result sizes and availability.
- qBittorrent API compatibility for Radarr/Sonarr queue tracking and imports.
- Configurable categories for multiple Arr instances.
- SQLite persistence, v1 JSON import, caching and global search throttling.
- Optional links from Arr results to the matching AirDC++ folder.
- Hardened, non-root Docker image for `linux/amd64` and `linux/arm64`.

## Requirements

- A running AirDC++ Web Client with its Web API reachable from the bridge.
- Docker Engine with Docker Compose v2.
- Radarr and/or Sonarr with access to the bridge address.
- A TMDB API key is optional but strongly recommended for translated and alternate titles.

The AirDC++ user needs permission to view hubs, search, browse file lists, manage the queue and start downloads.

## Quick start

Download `docker-compose.yml` and `.env.example`, then run:

```bash
cp .env.example .env
# Edit .env and replace every change-me value.
docker compose up -d
docker compose ps
curl http://localhost:8001/health/ready
```

The compose file uses `ghcr.io/antaneyes/airdcpp-torznab-bridge:beta`. Pin `BRIDGE_IMAGE_TAG=2.0.0-beta.3` in `.env` for fully reproducible upgrades.

If AirDC++ is another container on the same Docker network, set `AIRDCPP_URL=http://airdcpp:5600` and attach the bridge to that network. If AirDC++ publishes port 5600 on the Docker host, the default `http://host.docker.internal:5600` works with the included `extra_hosts` entry.

## Radarr and Sonarr

Add a **Torznab** indexer:

| Setting | Radarr | Sonarr |
| --- | --- | --- |
| URL | `http://bridge-host:8001/torznab` | `http://bridge-host:8001/torznab` |
| API key | `BRIDGE_API_KEY` | `BRIDGE_API_KEY` |
| Categories | Movies / `2000` | TV / `5000` |

Add a **qBittorrent** download client:

- Host and port: the bridge address and `8001`.
- Username/password: `BRIDGE_USERNAME` and `BRIDGE_PASSWORD`.
- Category: `radarr` or `sonarr` by default; it must exist in `DOWNLOAD_CATEGORIES`.
- Disable sequential download and first/last-piece prioritization.

When Arr sees a different download path than AirDC++, add a Remote Path Mapping whose host exactly matches the download client host, whose remote path is `SAVE_PATH`, and whose local path is the same directory as mounted in Arr.

If containers share a Docker network, use the service name and internal port instead: `airdcpp-bridge:8000`. `PUBLIC_URL` must still be an address that Radarr/Sonarr can reach when downloading an indexer result.

## Configuration

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `AIRDCPP_URL` | yes | `http://localhost:5600` | AirDC++ Web API base URL |
| `AIRDCPP_USER`, `AIRDCPP_PASS` | yes | empty | AirDC++ credentials |
| `BRIDGE_API_KEY` | yes | empty | Torznab and result-link API key |
| `BRIDGE_USERNAME`, `BRIDGE_PASSWORD` | yes | empty | qBittorrent-compatible login |
| `TMDB_API_KEY` | no | empty | Movie/series title enrichment |
| `SAVE_PATH` | no | `/downloads` | Path reported to Arr |
| `DOWNLOAD_CATEGORIES` | no | `radarr,sonarr,radarr4k,sonarr4k` | Accepted qBittorrent categories |
| `PUBLIC_URL` | conditional | request URL | Bridge URL used for download links |
| `AIRDCPP_WEB_URL` | no | empty | Enables links to AirDC++ folders |
| `COMPLETED_RATIO` | no | `1.5` | Virtual ratio reported after completion |
| `ALLOW_FILE_DELETE` | no | `false` | Allows removal requests to delete downloaded data |
| `AIRDCPP_MAX_ACTIVE_SEARCHES` | no | `1` | Maximum simultaneous hub searches |
| `SEARCH_TIMEOUT` | no | `10` | Maximum seconds per search variant |
| `SEARCH_CACHE_TTL` | no | `300` | Positive result cache lifetime |
| `SEARCH_NEGATIVE_CACHE_TTL` | no | `30` | Empty result cache lifetime |
| `SEARCH_CACHE_SIZE` | no | `256` | Maximum cached searches |
| `SEARCH_MIN_ACCEPTED_RESULTS` | no | `5` | Result count before stopping variant expansion |
| `SEARCH_MAX_VARIANTS` | no | `4` | Maximum title variants per request |
| `SEARCH_MAX_RESULTS` | no | `1000` | Maximum AirDC++ results read |
| `SEASON_INSPECT_MAX` | no | `10` | Ambiguous folders inspected per season search |
| `SEASON_INSPECT_TIMEOUT` | no | `5` | File-list inspection timeout |
| `LOG_LEVEL` | no | `INFO` | Python logging level |
| `ALLOW_INSECURE` | no | `false` | Disables bridge authentication; isolated test networks only |

## Upgrade, troubleshooting and safety

- Existing v1 users must follow **[UPGRADING.md](UPGRADING.md)**. Do not point v2 at the old data directory without taking a backup first.
- `GET /health/live` checks the bridge process; `GET /health/ready` also checks AirDC++ connectivity.
- An Arr indexer test with no real query returns a clearly labelled validation item. It is never downloadable content.
- A search can take several seconds on first use. Repeated requests are normally served from cache.
- The bridge never deletes downloaded files unless `ALLOW_FILE_DELETE=true` and Arr explicitly requests deletion.

See [SECURITY.md](SECURITY.md) before exposing the service beyond a private LAN.

To update within the beta channel:

```bash
docker compose pull
docker compose up -d
curl http://localhost:8001/health/ready
```

Back up the data volume before changing between numbered beta releases. Use a numbered `BRIDGE_IMAGE_TAG` when automatic beta updates are not desired.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/pytest --cov=app
docker build -t airdcpp-torznab-bridge:local .
```

Licensed under [GPL-3.0](LICENSE).
