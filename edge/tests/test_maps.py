"""Maps work offline: Leaflet ships with the app and viewed map tiles are kept on disk."""
import os


class FakeResponse:
    ok = True
    content = b"\x89PNG" + b"0" * 200


def test_leaflet_is_bundled(client):
    for f in ("leaflet.js", "leaflet.css", "images/marker-icon.png"):
        assert client.get(f"/vendor/leaflet/{f}").status_code == 200
    html = client.get("/drone-control").get_data(as_text=True)
    assert "unpkg.com" not in html and "/vendor/leaflet/leaflet.js" in html and "/tiles/osm/{z}/{x}/{y}" in html


def test_tiles_are_saved_and_used_offline(d, client, monkeypatch):
    calls = []
    monkeypatch.setattr(d.requests, "get", lambda url, **k: calls.append(url) or FakeResponse())
    r = client.get("/tiles/osm/17/37000/47000")
    assert r.status_code == 200 and r.data == FakeResponse.content and "tile.openstreetmap.org/17/37000/47000.png" in calls[0]
    assert os.path.exists(os.path.join(d.TILE_DIR, "osm", "17", "37000", "47000.png"))

    def offline(url, **k):
        raise OSError("no internet")
    monkeypatch.setattr(d.requests, "get", offline)
    calls.clear()
    assert client.get("/tiles/osm/17/37000/47000").data == FakeResponse.content  # from disk
    assert client.get("/tiles/sat/17/37000/47001").status_code == 404  # never seen, no internet
    assert client.get("/tiles/other/1/0/0").status_code == 404
    assert client.get("/tiles/osm/2/9/0").status_code == 404  # outside the world
    d._tile_stats["at"] = 0
    assert d.map_cache_stats()["tiles"] >= 1


def test_satellite_tile_url_order(d, client, monkeypatch):
    calls = []
    monkeypatch.setattr(d.requests, "get", lambda url, **k: calls.append(url) or FakeResponse())
    client.get("/tiles/sat/18/100/200")
    assert calls[0].endswith("/tile/18/200/100")  # ArcGIS wants z/y/x
