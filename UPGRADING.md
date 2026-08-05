# Upgrading from v1 to v2

Changing only `:latest` to `:beta` is **not enough**. You can keep the address, host port `8000`, data directory, and existing Radarr/Sonarr entries, but v2 requires additional credentials and configuration.

For the complete step-by-step guide in Spanish, see [docs/es/UPGRADING.md](docs/es/UPGRADING.md).

## Before upgrading

1. Stop v1 and back up the directory or Docker volume mounted at `/app/data`.
2. Confirm that it contains `bridge_hashes.json`.
3. Do not run v1 and v2 against the same data directory at the same time.
4. Pin `2.0.0-beta.3` initially instead of using the moving `beta` tag.

## In-place upgrade (recommended)

This route preserves the old URL and port.

1. Stop v1 and copy its data:

   ```bash
   docker compose down
   cp -a data data.backup-v1
   sudo chown -R 10001:10001 data
   ```

   V2 runs as the unprivileged UID/GID `10001`; the ownership change allows it to create `bridge.db`. The backup retains the original ownership and v1 state for rollback.

2. Copy v2's `.env.example` to `.env`. At minimum, configure:

   ```env
   BRIDGE_IMAGE_TAG=2.0.0-beta.3
   BRIDGE_PORT=8000
   AIRDCPP_URL=http://host.docker.internal:5600
   AIRDCPP_USER=YOUR_AIRDCPP_USER
   AIRDCPP_PASS=YOUR_AIRDCPP_PASSWORD
   PUBLIC_URL=http://SERVER_IP:8000
   BRIDGE_API_KEY=A_LONG_RANDOM_KEY
   BRIDGE_USERNAME=arr
   BRIDGE_PASSWORD=A_DIFFERENT_LONG_PASSWORD
   SAVE_PATH=/downloads
   DOWNLOAD_CATEGORIES=airdcpp,radarr,sonarr
   ```

3. Use the v2 Compose service while retaining the v1 bind mount and host port:

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

   Restore any external Docker networks required by your existing deployment.

4. Pull, start, and verify v2:

   ```bash
   docker compose pull
   docker compose up -d
   docker compose logs --tail=100 airdcpp-bridge
   curl http://localhost:8000/health/ready
   ```

   A successful readiness response is `{"status":"ready"}`.

5. In every Radarr/Sonarr Torznab indexer, set the API key to `BRIDGE_API_KEY`. In every qBittorrent download-client entry pointing to the bridge, set the username and password to `BRIDGE_USERNAME` and `BRIDGE_PASSWORD`. Keep the existing host and port if they did not change.
6. Test the indexer and download client, run an interactive search, and verify one download before enabling automatic searches.

On first startup v2 copies `bridge_hashes.json` to `bridge_hashes.json.v1.bak`, imports hashes, bundles, categories, and completed items into `bridge.db`, and leaves the source JSON untouched. The import is idempotent.

## Parallel test

To test without immediately replacing v1:

1. Copy `data` to `data-v2`; never share the live directory.
2. Run v2 with a different container name and host port `8001`.
3. Set `PUBLIC_URL=http://SERVER_IP:8001` and mount `./data-v2:/app/data`.
4. Add the v2 indexer and download client temporarily to one Arr instance.
5. Do not send the same release to both bridges. Changes to either queue after the copy are not synchronized.
6. Once validated, stop v1 and optionally move v2 back to port `8000`.

## Docker named volumes

If v1 mounted a named volume at `/app/data`, identify it first:

```bash
docker inspect airdcpp-bridge --format '{{range .Mounts}}{{println .Name .Source .Destination}}{{end}}'
```

Back it up, then declare that exact volume as external in the v2 Compose file. Do not create a new empty volume and expect Docker to transfer `bridge_hashes.json` automatically.

With v1 stopped, grant v2's unprivileged user access to it:

```bash
docker run --rm \
  -v ACTUAL_VOLUME_NAME:/data \
  alpine chown -R 10001:10001 /data
```

Only change ownership after creating the volume backup.

## Rollback

1. Stop v2.
2. Preserve its failed data for diagnosis.
3. Restore the v1 backup and the Compose file from [`legacy-v1`](https://github.com/Antaneyes/airdcpp-torznab-bridge/tree/legacy-v1).
4. Re-enable the old Arr entries.

Never run v1 and v2 concurrently against the same state directory.
