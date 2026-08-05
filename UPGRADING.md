# Upgrading from v1 to v2

Version 2 replaces the v1 JSON state with SQLite and enables authentication by default. Back up the v1 data directory before starting.

For the Spanish guide, see [docs/es/UPGRADING.md](docs/es/UPGRADING.md).

## What changes

| v1 | v2 |
| --- | --- |
| `bridge_hashes.json` | `bridge.db` (the JSON file is imported automatically) |
| No Torznab authentication | `BRIDGE_API_KEY` is required |
| Download-client authentication was inconsistent | `BRIDGE_USERNAME` and `BRIDGE_PASSWORD` are required |
| Hard-coded TMDB key | Your optional `TMDB_API_KEY` |
| `AIRDCPP_CATEGORIES` | `DOWNLOAD_CATEGORIES` |
| `/downloads` was effectively fixed | `SAVE_PATH` and Remote Path Mapping are explicit |
| Default service port `8000` | Beta example uses host port `8001`; internal port remains `8000` |

If you used the old `airdcpp` category, include it explicitly: `DOWNLOAD_CATEGORIES=airdcpp,radarr,sonarr`.

## Recommended: parallel upgrade

1. Back up the old directory: `cp -a data data.backup-v1`.
2. Start v2 on port `8001` with a new volume and configure all new secrets.
3. Test `/health/ready`, then add the v2 indexer and download client to one Arr instance.
4. Keep v1 running until active v1 downloads are imported or completed.
5. Disable the v1 indexer/client and remove v1 only after the v2 workflow succeeds.

Parallel mode does not transfer the old queue because both bridges must not manage the same AirDC++ bundles simultaneously.

## In-place upgrade with state migration

1. Stop v1 and make a backup:

   ```bash
   docker compose down
   cp -a data data.backup-v1
   ```

2. Use the v2 image but retain the old bind mount and, if desired, the old host port:

   ```yaml
   ports:
     - "8000:8000"
   volumes:
     - ./data:/app/data
   ```

3. Add the v2 environment variables from `.env.example`. Set `PUBLIC_URL` to the address used by Arr.
4. Start v2. On first startup it copies `bridge_hashes.json` to `bridge_hashes.json.v1.bak`, imports it into `bridge.db`, and leaves the source JSON untouched.
5. Update the Torznab API key and qBittorrent username/password in Radarr/Sonarr. If the host or port changed, update Remote Path Mapping too.
6. Confirm `GET /health/ready`, run both Arr connection tests, then check active downloads before enabling automatic searches.

The importer is idempotent: restarting v2 will not duplicate records.

## Moving old state into the named volume

If you prefer the new `bridge-data` volume, copy the v1 JSON before first startup:

```bash
docker compose create
docker run --rm \
  -v "$(pwd)/data:/source:ro" \
  -v airdcpp-torznab-bridge_bridge-data:/target \
  busybox cp /source/bridge_hashes.json /target/bridge_hashes.json
docker compose up -d
```

The actual volume name includes the Compose project name; verify it with `docker volume ls`.

## Rollback

1. Stop v2.
2. Restore the original v1 compose file or use the `legacy-v1` branch.
3. Restore `data.backup-v1` if v1 state was modified after the backup.
4. Re-enable the old Arr entries.

Do not run v1 and an in-place-migrated v2 against the same state directory at the same time.
