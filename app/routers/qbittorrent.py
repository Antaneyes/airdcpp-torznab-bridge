import hashlib
import time
import urllib.parse

from fastapi import APIRouter, Request, Response

from app.core.security import valid_login
from app.models import DownloadRecord, DownloadState
from app.services.airdcpp import AirDCError

router = APIRouter(prefix="/api/v2")


def _categories(request: Request) -> tuple[str, ...]:
    return request.app.state.settings.categories


def _sid(request: Request) -> str:
    settings = request.app.state.settings
    raw = f"{settings.bridge_username}:{settings.bridge_password.get_secret_value()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _authorized(request: Request) -> bool:
    settings = request.app.state.settings
    return settings.allow_insecure or settings.testing or request.cookies.get("SID") == _sid(request)


def _auth_error() -> Response:
    return Response("Forbidden", status_code=403, media_type="text/plain")


@router.post("/auth/login")
@router.post("/auth/login/")
async def login(request: Request) -> Response:
    form = await request.form()
    settings = request.app.state.settings
    valid = valid_login(str(form.get("username", "")), str(form.get("password", "")), settings)
    response = Response("Ok." if valid else "Fails.", status_code=200, media_type="text/plain")
    if valid:
        response.set_cookie("SID", _sid(request), httponly=True, samesite="strict", path="/")
    return response


@router.post("/auth/logout")
async def logout() -> Response:
    response = Response("Ok.", media_type="text/plain")
    response.delete_cookie("SID", path="/")
    return response


@router.get("/app/version")
async def app_version(request: Request) -> Response:
    return _auth_error() if not _authorized(request) else Response("v4.3.9", media_type="text/plain")


@router.get("/app/webapiVersion")
@router.get("/app/webApiVersion")
async def api_version(request: Request) -> Response:
    return _auth_error() if not _authorized(request) else Response("2.8.2", media_type="text/plain")


@router.get("/app/preferences")
async def preferences(request: Request):
    if not _authorized(request):
        return _auth_error()
    return {"save_path": request.app.state.settings.save_path, "listen_port": 8000, "queueing_enabled": True}


@router.get("/torrents/categories")
async def categories(request: Request):
    if not _authorized(request):
        return _auth_error()
    path = request.app.state.settings.save_path
    return {name: {"name": name, "savePath": path} for name in _categories(request)}


async def _refresh(request: Request, category: str | None = None) -> list[DownloadRecord]:
    repository = request.app.state.repository
    records = await repository.list_downloads(category)
    bundles = await request.app.state.airdcpp.bundles()
    by_id = {str(b.get("id")): b for b in bundles}
    refreshed: list[DownloadRecord] = []
    for record in records:
        bundle = by_id.get(record.bundle_id or "")
        if bundle:
            size = int(float(bundle.get("size", record.size)))
            downloaded = int(float(bundle.get("downloaded_bytes", 0)))
            progress = downloaded / size if size else 0
            completed = bool(bundle.get("status", {}).get("completed")) or progress >= 0.999
            record.size = size
            record.downloaded = downloaded
            record.progress = min(1.0, progress)
            record.speed = int(float(bundle.get("speed", 0)))
            record.eta = int(float(bundle.get("seconds_left", 8640000)))
            record.name = str(bundle.get("name", record.name))
            if completed:
                record.state = DownloadState.COMPLETED
                record.progress = 1.0
                record.downloaded = size
                record.completed_on = int(bundle.get("time_finished") or record.completed_on or time.time())
            elif progress > 0:
                record.state = DownloadState.DOWNLOADING
            await repository.save_download(record)
        refreshed.append(record)
    return refreshed


def _qbit_item(record: DownloadRecord, save_path: str, ratio: float) -> dict:
    completed = record.state == DownloadState.COMPLETED
    state = "uploading" if completed else ("downloading" if record.progress > 0 else "stalledDL")
    uploaded = int(record.size * ratio) if completed else 0
    return {
        "hash": record.download_id,
        "name": record.name,
        "size": record.size,
        "progress": record.progress,
        "dlspeed": record.speed,
        "upspeed": 0,
        "eta": 0 if completed else record.eta,
        "state": state,
        "amount_left": max(0, record.size - record.downloaded),
        "completed": record.completed_on,
        "save_path": save_path,
        "content_path": f"{save_path.rstrip('/')}/{record.name}",
        "category": record.category,
        "tags": "",
        "num_seeds": 0,
        "num_leechs": 0,
        "added_on": record.added_on,
        "completion_on": record.completed_on,
        "downloaded": record.downloaded,
        "uploaded": uploaded,
        "ratio": ratio if completed else 0.0,
        "seeding_time": 0,
    }


@router.get("/torrents/info")
async def torrent_info(request: Request, category: str | None = None):
    if not _authorized(request):
        return _auth_error()
    try:
        records = await _refresh(request, category)
    except AirDCError as exc:
        return Response(str(exc), status_code=502, media_type="text/plain")
    settings = request.app.state.settings
    return [_qbit_item(record, settings.save_path, settings.completed_ratio) for record in records]


@router.get("/sync/maindata")
async def main_data(request: Request, category: str | None = None):
    result = await torrent_info(request, category)
    if isinstance(result, Response):
        return result
    path = request.app.state.settings.save_path
    return {
        "full_update": True,
        "torrents": {item["hash"]: item for item in result},
        "categories": {name: {"name": name, "savePath": path} for name in _categories(request)},
        "server_state": {"free_space_on_disk": -1},
    }


@router.get("/torrents/properties")
async def torrent_properties(request: Request, hash: str):
    if not _authorized(request):
        return _auth_error()
    record = await request.app.state.repository.get_download(hash)
    if not record:
        return Response("Not found", status_code=404)
    return {
        "save_path": request.app.state.settings.save_path,
        "creation_date": record.added_on,
        "completion_date": record.completed_on,
        "total_size": record.size,
        "piece_size": 0,
        "is_seed": record.state == DownloadState.COMPLETED,
    }


@router.get("/torrents/files")
async def torrent_files(request: Request, hash: str):
    if not _authorized(request):
        return _auth_error()
    record = await request.app.state.repository.get_download(hash)
    if not record:
        return []
    return [
        {
            "index": 0,
            "name": record.name,
            "size": record.size,
            "progress": record.progress,
            "priority": 1,
            "is_seed": record.state == DownloadState.COMPLETED,
            "piece_range": [0, 0],
            "availability": 1.0 if record.state == DownloadState.COMPLETED else 0.0,
        }
    ]


@router.post("/torrents/add")
async def torrent_add(request: Request) -> Response:
    if not _authorized(request):
        return _auth_error()
    form = await request.form()
    urls = str(form.get("urls", ""))
    category = str(form.get("category") or "sonarr").lower()
    if category not in _categories(request):
        return Response("Categoría no soportada", status_code=400)
    if not urls:
        return Response("Solo se admiten magnet URLs", status_code=400)
    success = False
    for url in urls.splitlines():
        parsed = urllib.parse.urlparse(url.strip())
        params = urllib.parse.parse_qs(parsed.query)
        xt = params.get("xt", [""])[0]
        release_id = xt.rsplit(":", 1)[-1]
        release = await request.app.state.repository.get_release(release_id)
        if not release:
            continue
        try:
            bundle_id = await request.app.state.airdcpp.download(release)
            await request.app.state.repository.save_download(
                DownloadRecord(
                    download_id=release_id,
                    release_id=release_id,
                    bundle_id=bundle_id,
                    category=category,
                    name=release.name,
                    size=release.size,
                    added_on=int(time.time()),
                )
            )
            success = True
        except AirDCError:
            continue
    return Response("Ok." if success else "Fallo.", status_code=200 if success else 502, media_type="text/plain")


@router.post("/torrents/delete")
async def torrent_delete(request: Request) -> Response:
    if not _authorized(request):
        return _auth_error()
    form = await request.form()
    hashes = str(form.get("hashes", ""))
    delete_files = str(form.get("deleteFiles", "false")).lower() == "true"
    for download_id in hashes.split("|"):
        record = await request.app.state.repository.get_download(download_id)
        if not record:
            continue
        if record.bundle_id:
            try:
                await request.app.state.airdcpp.remove_bundle(record.bundle_id, delete_files)
            except AirDCError as exc:
                return Response(str(exc), status_code=502)
        await request.app.state.repository.mark_removed(download_id)
    return Response("Ok.", media_type="text/plain")


@router.post("/torrents/setCategory")
async def set_category(request: Request) -> Response:
    if not _authorized(request):
        return _auth_error()
    form = await request.form()
    category = str(form.get("category", "")).strip().lower()
    if category not in _categories(request):
        return Response("Categoría no soportada", status_code=400)
    for download_id in str(form.get("hashes", "")).split("|"):
        await request.app.state.repository.update_category(download_id, category)
    return Response("Ok.", media_type="text/plain")


@router.post("/torrents/setShareLimits")
@router.post("/torrents/topPrio")
@router.post("/torrents/setForceStart")
async def accepted_noop(request: Request) -> Response:
    return _auth_error() if not _authorized(request) else Response("Ok.", media_type="text/plain")


@router.post("/torrents/createCategory")
async def create_category(request: Request) -> Response:
    if not _authorized(request):
        return _auth_error()
    form = await request.form()
    category = str(form.get("category", "")).strip().lower()
    if category not in _categories(request):
        return Response("Categoría no soportada", status_code=400)
    return Response("Ok.", media_type="text/plain")
