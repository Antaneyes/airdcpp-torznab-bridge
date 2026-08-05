import json
import shutil
import time
from pathlib import Path

import aiosqlite

from app.models import DownloadRecord, DownloadState, SearchResult

SCHEMA_VERSION = 7


class Repository:
    def __init__(self, path: Path):
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            version_row = await (await db.execute("PRAGMA user_version")).fetchone()
            version = int(version_row[0]) if version_row else 0
            if self.path.stat().st_size > 0 and version < SCHEMA_VERSION:
                backup = self.path.with_suffix(f".db.v{version}.bak-{int(time.time())}")
                shutil.copy2(self.path, backup)
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS hashes (
                    tth TEXT PRIMARY KEY,
                    hex TEXT UNIQUE NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_hashes_hex ON hashes(hex);
                CREATE TABLE IF NOT EXISTS bundles (
                    bundle_id TEXT PRIMARY KEY,
                    tth TEXT NOT NULL,
                    category TEXT DEFAULT 'radarr'
                );
                CREATE TABLE IF NOT EXISTS finished (
                    tth TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS releases (
                    release_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    tth TEXT,
                    item_type TEXT NOT NULL,
                    source_id TEXT,
                    query TEXT NOT NULL,
                    published_at INTEGER NOT NULL DEFAULT 0,
                    availability INTEGER NOT NULL DEFAULT 1,
                    languages TEXT NOT NULL DEFAULT '[]',
                    source_name TEXT,
                    source_path TEXT,
                    source_cid TEXT,
                    source_hub_url TEXT,
                    download_via_filelist INTEGER NOT NULL DEFAULT 0,
                    selected_files TEXT NOT NULL DEFAULT '[]',
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS downloads (
                    download_id TEXT PRIMARY KEY,
                    release_id TEXT NOT NULL,
                    bundle_id TEXT UNIQUE,
                    category TEXT NOT NULL,
                    name TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    downloaded INTEGER NOT NULL DEFAULT 0,
                    speed INTEGER NOT NULL DEFAULT 0,
                    eta INTEGER NOT NULL DEFAULT 8640000,
                    added_on INTEGER NOT NULL,
                    completed_on INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(release_id) REFERENCES releases(release_id)
                );
                CREATE INDEX IF NOT EXISTS idx_downloads_bundle ON downloads(bundle_id);
                CREATE INDEX IF NOT EXISTS idx_downloads_category ON downloads(category);
                """
            )
            columns = {row[1] for row in await (await db.execute("PRAGMA table_info(releases)")).fetchall()}
            if "published_at" not in columns:
                await db.execute("ALTER TABLE releases ADD COLUMN published_at INTEGER NOT NULL DEFAULT 0")
            if "availability" not in columns:
                await db.execute("ALTER TABLE releases ADD COLUMN availability INTEGER NOT NULL DEFAULT 1")
            if "languages" not in columns:
                await db.execute("ALTER TABLE releases ADD COLUMN languages TEXT NOT NULL DEFAULT '[]'")
            for column in ("source_name", "source_path", "source_cid", "source_hub_url"):
                if column not in columns:
                    await db.execute(f"ALTER TABLE releases ADD COLUMN {column} TEXT")
            if "download_via_filelist" not in columns:
                await db.execute("ALTER TABLE releases ADD COLUMN download_via_filelist INTEGER NOT NULL DEFAULT 0")
            if "selected_files" not in columns:
                await db.execute("ALTER TABLE releases ADD COLUMN selected_files TEXT NOT NULL DEFAULT '[]'")
            await self._migrate_legacy(db)
            await db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            await db.commit()

    async def _migrate_legacy(self, db: aiosqlite.Connection) -> None:
        rows = await (await db.execute("SELECT bundle_id, tth, category FROM bundles")).fetchall()
        for bundle_id, tth, category in rows:
            hex_row = await (await db.execute("SELECT hex FROM hashes WHERE tth=?", (tth,))).fetchone()
            if not hex_row:
                continue
            release_id = hex_row[0]
            finished_row = await (await db.execute("SELECT data FROM finished WHERE tth=?", (tth,))).fetchone()
            data = json.loads(finished_row[0]) if finished_row else {}
            name = data.get("name", f"legacy-{bundle_id}")
            size = int(data.get("size", 0))
            await db.execute(
                """INSERT OR IGNORE INTO releases
                (release_id,name,size,tth,item_type,source_id,query,published_at,availability,languages,
                 source_name,source_path,source_cid,source_hub_url,download_via_filelist,selected_files,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (release_id, name, size, tth, "file", None, "legacy", 0, 1, "[]", None, None, None, None, 0, "[]",
                 int(time.time())),
            )
            state = DownloadState.COMPLETED if finished_row else DownloadState.QUEUED
            await db.execute(
                """INSERT OR IGNORE INTO downloads
                (download_id,release_id,bundle_id,category,name,size,state,progress,downloaded,speed,eta,added_on,completed_on)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    release_id,
                    release_id,
                    bundle_id,
                    category or "radarr",
                    name,
                    size,
                    state,
                    float(data.get("progress", 1 if finished_row else 0)),
                    int(data.get("downloaded", size if finished_row else 0)),
                    0,
                    0 if finished_row else 8640000,
                    int(data.get("added_on", time.time())),
                    int(data.get("completion_on", 0)),
                ),
            )

    async def count_hashes(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute("SELECT COUNT(*) FROM hashes")).fetchone()
            return int(row[0]) if row else 0

    async def save_hash(self, tth: str, hex_hash: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR IGNORE INTO hashes(tth,hex) VALUES(?,?)", (tth, hex_hash))
            await db.commit()

    async def tth_for_hash(self, hex_hash: str) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute("SELECT tth FROM hashes WHERE hex=?", (hex_hash,))).fetchone()
            return row[0] if row else None

    async def save_release(self, result: SearchResult) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO releases
                (release_id,name,size,tth,item_type,source_id,query,published_at,availability,languages,
                 source_name,source_path,source_cid,source_hub_url,download_via_filelist,selected_files,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    result.release_id,
                    result.name,
                    result.size,
                    result.tth,
                    result.item_type,
                    str(result.source_id) if result.source_id is not None else None,
                    result.query,
                    result.published_at,
                    result.availability,
                    json.dumps(result.languages),
                    result.source_name,
                    result.source_path,
                    result.source_cid,
                    result.source_hub_url,
                    int(result.download_via_filelist),
                    json.dumps(result.selected_files),
                    int(time.time()),
                ),
            )
            await db.commit()

    async def get_release(self, release_id: str) -> SearchResult | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM releases WHERE release_id=?", (release_id,))).fetchone()
            if not row:
                return None
            data = {
                k: row[k]
                for k in (
                    "release_id",
                    "name",
                    "size",
                    "tth",
                    "item_type",
                    "source_id",
                    "query",
                    "published_at",
                    "source_name",
                    "source_path",
                    "source_cid",
                    "source_hub_url",
                    "download_via_filelist",
                )
            }
            data["availability"] = row["availability"]
            data["languages"] = json.loads(row["languages"])
            data["selected_files"] = json.loads(row["selected_files"])
            return SearchResult(**data)

    async def save_download(self, record: DownloadRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO downloads VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(record.model_dump().values()),
            )
            await db.commit()

    async def list_downloads(self, category: str | None = None) -> list[DownloadRecord]:
        query = "SELECT * FROM downloads WHERE state != 'removed'"
        params: tuple[str, ...] = ()
        if category:
            query += " AND lower(category)=lower(?)"
            params = (category,)
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(query, params)).fetchall()
            return [DownloadRecord(**dict(row)) for row in rows]

    async def get_download(self, download_id: str) -> DownloadRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM downloads WHERE download_id=?", (download_id,))).fetchone()
            return DownloadRecord(**dict(row)) if row else None

    async def mark_removed(self, download_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE downloads SET state='removed' WHERE download_id=?", (download_id,))
            await db.commit()

    async def update_category(self, download_id: str, category: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE downloads SET category=? WHERE download_id=?", (category, download_id))
            await db.commit()
