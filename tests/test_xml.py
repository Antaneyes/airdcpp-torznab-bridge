import xml.etree.ElementTree as ET

from app.models import SearchResult
from app.utils.xml import caps_xml, error_xml, feed_xml


def test_caps_and_empty_feed_are_valid_xml():
    assert ET.fromstring(caps_xml()).tag == "caps"
    feed = ET.fromstring(feed_xml([], "http://bridge", "key", "2000", None, None))
    assert feed.findall("./channel/item") == []
    assert ET.fromstring(error_xml(900, "upstream failed")).attrib["code"] == "900"


def test_feed_contains_stable_release_contract():
    result = SearchResult(
        release_id="a" * 40,
        name="Movie & More Dual.mkv",
        size=100,
        tth="TTH",
        published_at=1_403_129_739,
        availability=4,
    )
    root = ET.fromstring(feed_xml([result], "http://bridge", "secret", "2000", None, None, "tt0230011", "10865"))
    item = root.find("./channel/item")
    assert item is not None
    assert item.findtext("title") == "Movie & More Dual.mkv"
    assert item.findtext("guid") == "a" * 40
    enclosure = item.find("enclosure")
    assert enclosure is not None
    assert enclosure.attrib["url"].endswith("apikey=secret")
    assert item.findtext("pubDate") == "Wed, 18 Jun 2014 22:15:39 GMT"
    languages = [
        attr.attrib["value"]
        for attr in item.findall("{http://torznab.com/schemas/2015/feed}attr")
        if attr.attrib["name"] == "language"
    ]
    assert languages == ["Spanish"]
    attrs = {
        attr.attrib["name"]: attr.attrib["value"] for attr in item.findall("{http://torznab.com/schemas/2015/feed}attr")
    }
    assert attrs["seeders"] == "4"
    assert "tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce" in attrs["magneturl"]
    assert attrs["imdb"] == "0230011"
    assert attrs["tmdbid"] == "10865"
