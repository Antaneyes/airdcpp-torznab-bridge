import json
import sqlite3

from app.models import DownloadRecord, SearchResult
from app.services.database import Repository


async def test_migrates_legacy_database_without_changing_hash(tmp_path):
    path = tmp_path / "bridge.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE hashes(tth TEXT PRIMARY KEY, hex TEXT UNIQUE NOT NULL);
        CREATE TABLE bundles(bundle_id TEXT PRIMARY KEY, tth TEXT NOT NULL, category TEXT DEFAULT 'radarr');
        CREATE TABLE finished(tth TEXT PRIMARY KEY, data TEXT NOT NULL);
        """
    )
    db.execute("INSERT INTO hashes VALUES(?,?)", ("TTHVALUE", "a" * 40))
    db.execute("INSERT INTO bundles VALUES(?,?,?)", ("12", "TTHVALUE", "radarr"))
    db.execute("INSERT INTO finished VALUES(?,?)", ("TTHVALUE", json.dumps({"name": "Movie.mkv", "size": 10})))
    db.commit()
    db.close()

    repository = Repository(path)
    await repository.initialize()
    assert await repository.tth_for_hash("a" * 40) == "TTHVALUE"
    record = await repository.get_download("a" * 40)
    assert record is not None
    assert record.name == "Movie.mkv"
    assert record.state == "completed"
    assert list(tmp_path.glob("bridge.db.v0.bak-*"))


async def test_imports_v1_json_idempotently_and_keeps_backup(tmp_path):
    legacy = {
        "hashes": {"TTH-ACTIVE": "a" * 40, "TTH-DONE": "b" * 40},
        "bundles": {"12": "TTH-ACTIVE", "13": "TTH-DONE"},
        "categories": {"12": "sonarr", "13": "airdcpp"},
        "finished": {"TTH-DONE": {"name": "Finished.mkv", "size": 42, "progress": 1}},
    }
    (tmp_path / "bridge_hashes.json").write_text(json.dumps(legacy), encoding="utf-8")

    repository = Repository(tmp_path / "bridge.db")
    await repository.initialize()
    await repository.initialize()

    assert await repository.tth_for_hash("a" * 40) == "TTH-ACTIVE"
    active = await repository.get_download("a" * 40)
    finished = await repository.get_download("b" * 40)
    assert active is not None and active.bundle_id == "12" and active.category == "sonarr"
    assert finished is not None and finished.name == "Finished.mkv" and finished.category == "airdcpp"
    assert finished.state == "completed"
    assert (tmp_path / "bridge_hashes.json.v1.bak").read_text(encoding="utf-8") == json.dumps(legacy)
    assert len(await repository.list_downloads()) == 2


async def test_repository_crud(tmp_path):
    repository = Repository(tmp_path / "new.db")
    await repository.initialize()
    release = SearchResult(
        release_id="b" * 40,
        name="Show.mkv",
        size=20,
        tth="TTH2",
        published_at=1_403_129_739,
    )
    await repository.save_release(release)
    await repository.save_hash("TTH2", release.release_id)
    assert await repository.get_release(release.release_id) == release
    record = DownloadRecord(
        download_id=release.release_id,
        release_id=release.release_id,
        bundle_id="2",
        category="sonarr",
        name=release.name,
        size=release.size,
        added_on=1,
    )
    await repository.save_download(record)
    assert len(await repository.list_downloads("sonarr")) == 1
    await repository.update_category(record.download_id, "radarr")
    updated = await repository.get_download(record.download_id)
    assert updated is not None
    assert updated.category == "radarr"
    await repository.mark_removed(record.download_id)
    assert await repository.list_downloads() == []
