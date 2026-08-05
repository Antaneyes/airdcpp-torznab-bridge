import email.utils
import time
import urllib.parse
import xml.etree.ElementTree as ET

from app.models import SearchResult
from app.utils.text import detect_languages

TORZNAB_NS = "http://torznab.com/schemas/2015/feed"
COMPAT_TRACKER = "udp://tracker.opentrackr.org:1337/announce"
ET.register_namespace("torznab", TORZNAB_NS)


def caps_xml() -> str:
    root = ET.Element("caps")
    ET.SubElement(root, "server", version="2.0", title="AirDC++ Bridge")
    ET.SubElement(root, "limits", max="1000", default="100")
    ET.SubElement(root, "registration", available="no", open="no")
    searching = ET.SubElement(root, "searching")
    ET.SubElement(searching, "search", available="yes", supportedParams="q")
    ET.SubElement(searching, "tv-search", available="yes", supportedParams="q,season,ep,imdbid,tvdbid")
    ET.SubElement(searching, "movie-search", available="yes", supportedParams="q,imdbid,tmdbid")
    categories = ET.SubElement(root, "categories")
    movies = ET.SubElement(categories, "category", id="2000", name="Movies")
    ET.SubElement(movies, "subcat", id="2040", name="Movies/HD")
    tv = ET.SubElement(categories, "category", id="5000", name="TV")
    ET.SubElement(tv, "subcat", id="5040", name="TV/HD")
    return _serialize(root)


def feed_xml(
    results: list[SearchResult],
    base_url: str,
    api_key: str,
    category: str,
    season: int | None,
    episode: int | None,
    imdb_id: str | None = None,
    tmdb_id: str | None = None,
    tvdb_id: str | None = None,
    browse_enabled: bool = False,
) -> str:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "AirDC++ Bridge"
    ET.SubElement(channel, "description").text = "Resultados de AirDC++"
    ET.SubElement(channel, "link").text = base_url
    for result in results:
        languages = list(dict.fromkeys(result.languages + detect_languages(result.name)))
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = result.name
        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = result.release_id
        encoded_name = urllib.parse.quote(result.name, safe="")
        tracker = urllib.parse.quote(COMPAT_TRACKER, safe="")
        magnet = f"magnet:?xt=urn:btih:{result.release_id}&dn={encoded_name}&tr={tracker}"
        download = f"{base_url}/download/{result.release_id}.torrent?name={encoded_name}"
        if api_key:
            download += "&apikey=" + urllib.parse.quote(api_key, safe="")
        ET.SubElement(item, "link").text = magnet
        comments = f"{base_url}/browse/{result.release_id}" if browse_enabled else base_url
        ET.SubElement(item, "comments").text = comments
        published_at = result.published_at or int(time.time())
        ET.SubElement(item, "pubDate").text = email.utils.formatdate(published_at, usegmt=True)
        ET.SubElement(item, "size").text = str(result.size)
        ET.SubElement(item, "enclosure", url=download, length=str(result.size), type="application/x-bittorrent")
        attrs = {
            "category": "5000" if season is not None or category.startswith("5") else "2000",
            "size": str(result.size),
            "infohash": result.release_id,
            "magneturl": magnet,
            "seeders": str(result.availability),
            "peers": str(result.availability),
            "downloadvolumefactor": "0",
            "uploadvolumefactor": "1",
        }
        if season is not None:
            attrs["season"] = str(season)
        if episode is not None:
            attrs["episode"] = str(episode)
        if imdb_id:
            attrs["imdb"] = imdb_id.removeprefix("tt")
        if tmdb_id:
            attrs["tmdbid"] = tmdb_id
        if tvdb_id:
            attrs["tvdbid"] = tvdb_id
        for name, value in attrs.items():
            ET.SubElement(item, f"{{{TORZNAB_NS}}}attr", name=name, value=value)
        for language in languages:
            ET.SubElement(item, f"{{{TORZNAB_NS}}}attr", name="language", value=language)
    return _serialize(rss)


def error_xml(code: int, description: str) -> str:
    return _serialize(ET.Element("error", code=str(code), description=description))


def _serialize(element: ET.Element) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(element, encoding="unicode")
