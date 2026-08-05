# Changelog

All notable changes are documented here. This project follows semantic versioning while allowing breaking changes between beta releases.

## [2.0.0-beta.3] - 2026-08-05

### Added

- Searches retry title variants without diacritics for hubs that distinguish accented text.
- Season searches prioritize directory results before falling back to mixed result types.
- A documented design for optional synthetic RSS support is preserved for future work.

### Fixed

- Valid season folders are less likely to be hidden by a hub's per-user limit on individual file results.

## [2.0.0-beta.2] - 2026-08-05

### Added

- Season and episode search support for nested and mixed-season folders.
- Selective AirDC++ bundles that download only the requested season.
- Clickable links from Arr results to the source folder in AirDC++.
- Automatic, idempotent import of v1 `bridge_hashes.json` state.
- Configurable public URLs, download categories, save paths and virtual ratio.
- Bilingual install and upgrade documentation.

### Changed

- Rewritten as a modular asynchronous FastAPI application with SQLite persistence.
- Stricter title/year relevance, language hints and real AirDC++ publication dates.
- Authentication is required by default for Torznab and qBittorrent-compatible APIs.
- Docker container runs read-only as an unprivileged user with all capabilities dropped.

### Fixed

- Arr indexer validation no longer masquerades as a real movie result.
- Short titles, translated titles and folders containing multiple seasons are handled safely.
- An already-open AirDC++ file list is reused safely when it is already at the required folder.
- Completed downloads report compatible queue state, content paths and ratio.

### Known limitations

- Language detection depends on explicit release-name hints or reliable title metadata.
- The AirDC++ date is the best date exposed by the hub and may be much older than the upload date.
- Folder inspection can fail when a remote user's file list is unavailable or already open in another session.
- v2 remains a beta until selective season downloads have received broader real-world testing.
