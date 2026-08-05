import urllib.parse

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from app import __version__
from app.core.security import validate_api_key
from app.services.airdcpp import AirDCError
from app.utils.xml import COMPAT_TRACKER, error_xml

router = APIRouter()


@router.get("/browse/{release_id}")
async def browse_release(release_id: str, request: Request) -> Response:
    validate_api_key(request, request.app.state.settings)
    release = await request.app.state.repository.get_release(release_id)
    if not release:
        return Response("El resultado ha caducado o no existe", status_code=404)
    try:
        location = await request.app.state.airdcpp.open_filelist_location(release)
    except AirDCError as exc:
        return Response(str(exc), status_code=502)
    return RedirectResponse(location, status_code=302)


@router.get("/health")
@router.get("/health/live")
async def live(request: Request) -> dict:
    return {"status": "ok", "version": __version__, "hashes": await request.app.state.repository.count_hashes()}


@router.get("/health/ready")
async def ready(request: Request) -> Response:
    ok = await request.app.state.airdcpp.ready()
    return Response(
        content='{"status":"ready"}' if ok else '{"status":"unavailable"}',
        status_code=200 if ok else 503,
        media_type="application/json",
    )


@router.get("/download/{release_id}")
@router.get("/download/{release_id}.torrent")
async def download_redirect(request: Request, release_id: str, name: str = "file", apikey: str = "") -> Response:
    if release_id.endswith(".torrent"):
        release_id = release_id[:-8]
    settings = request.app.state.settings
    if not (settings.allow_insecure or settings.testing) and apikey != settings.bridge_api_key.get_secret_value():
        return Response(error_xml(100, "API key inválida"), status_code=401, media_type="application/xml")
    if not await request.app.state.repository.get_release(release_id):
        return Response("Resultado caducado o desconocido", status_code=404)
    tracker = urllib.parse.quote(COMPAT_TRACKER, safe="")
    magnet = f"magnet:?xt=urn:btih:{release_id}&dn={urllib.parse.quote(name, safe='')}&tr={tracker}"
    return Response(status_code=302, headers={"Location": magnet})
