# Security policy

## Supported versions

Security fixes are provided for the latest published v2 beta. The legacy v1 branch is preserved for rollback but is not supported for security fixes.

## Deployment

- Do not expose the bridge or AirDC++ Web Client directly to the Internet.
- Keep `ALLOW_INSECURE=false` and use long, unique values for all bridge and AirDC++ credentials.
- Restrict host firewall access to the Radarr/Sonarr hosts or Docker networks that need it.
- Keep `ALLOW_FILE_DELETE=false` unless remote deletion is explicitly required.
- Treat Torznab URLs as secrets because they may contain the API key.

The health endpoints intentionally require no authentication and disclose only status, version and the number of known hashes.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting feature for this repository. Do not open a public issue containing credentials, private hub addresses, file-list links or exploit details.
