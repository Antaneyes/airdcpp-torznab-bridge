from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.models import SearchResult
from app.services.airdcpp import AirDCError
from app.utils.xml import caps_xml, error_xml, feed_xml

router = APIRouter()


@router.get("/api")
@router.get("/torznab")
@router.get("/torznab/api")
async def torznab(
    request: Request,
    t: str,
    q: str | None = None,
    cat: str | None = None,
    imdbid: str | None = None,
    tmdbid: str | None = None,
    tvdbid: str | None = None,
    season: Annotated[int | None, Query(ge=0)] = None,
    ep: Annotated[int | None, Query(ge=0)] = None,
    apikey: str = "",
) -> Response:
    settings = request.app.state.settings
    expected = settings.bridge_api_key.get_secret_value()
    if not (settings.allow_insecure or settings.testing) and apikey != expected:
        return Response(error_xml(100, "API key inválida"), status_code=401, media_type="application/xml")
    if t == "caps":
        return Response(caps_xml(), media_type="application/xml")
    if t not in {"search", "tvsearch", "movie", "movie-search"}:
        return Response(error_xml(200, "Operación no soportada"), status_code=400, media_type="application/xml")
    if not any((q, imdbid, tmdbid, tvdbid)):
        validation = SearchResult(
            release_id="0" * 40,
            name="[AirDC++ Bridge] Resultado de validación (no descargar)",
            size=1,
            item_type="validation",
        )
        base_url = str(request.base_url).rstrip("/")
        xml = feed_xml([validation], base_url, apikey, cat or ("5000" if season is not None else "2000"), season, ep)
        return Response(xml, media_type="application/xml")
    try:
        results = await request.app.state.search_service.search(q, cat, imdbid, tmdbid, tvdbid, season, ep)
        base_url = str(request.base_url).rstrip("/")
        xml = feed_xml(
            results,
            base_url,
            apikey,
            cat or ("5000" if season is not None else "2000"),
            season,
            ep,
            imdbid,
            tmdbid,
            tvdbid,
        )
        return Response(xml, media_type="application/xml")
    except AirDCError as exc:
        return Response(error_xml(900, str(exc)), status_code=503, media_type="application/xml")
