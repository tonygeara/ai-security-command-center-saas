"""Distances and bearings between GPS points."""
import math


def _distance_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def _bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)))


# ----- UTM (WGS84), to place georeferenced 3D site maps (OpenDroneMap works in UTM metres) -----
_A, _F, _K0 = 6378137.0, 1 / 298.257223563, 0.9996
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)


def utm_zone(lat, lon):
    return int((lon + 180) // 6) + 1, lat >= 0


def latlon_to_utm(lat, lon, zone=None):
    """(easting, northing, zone, north) for a WGS84 point (Snyder's transverse Mercator series)."""
    zone, north = (zone, lat >= 0) if zone else utm_zone(lat, lon)
    phi, lam = math.radians(lat), math.radians(lon - (zone * 6 - 183))
    n = _A / math.sqrt(1 - _E2 * math.sin(phi) ** 2)
    t, c = math.tan(phi) ** 2, _EP2 * math.cos(phi) ** 2
    a = math.cos(phi) * lam
    m = _A * ((1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256) * phi
              - (3 * _E2 / 8 + 3 * _E2 ** 2 / 32 + 45 * _E2 ** 3 / 1024) * math.sin(2 * phi)
              + (15 * _E2 ** 2 / 256 + 45 * _E2 ** 3 / 1024) * math.sin(4 * phi) - (35 * _E2 ** 3 / 3072) * math.sin(6 * phi))
    e = _K0 * n * (a + (1 - t + c) * a ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * _EP2) * a ** 5 / 120) + 500000.0
    nn = _K0 * (m + n * math.tan(phi) * (a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a ** 4 / 24
                                         + (61 - 58 * t + t * t + 600 * c - 330 * _EP2) * a ** 6 / 720))
    return e, (nn if north else nn + 10000000.0), zone, north


def utm_to_latlon(e, n, zone, north=True):
    """WGS84 (lat, lon) of a UTM point."""
    x, y = e - 500000.0, n if north else n - 10000000.0
    m = y / _K0
    mu = m / (_A * (1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    n1 = _A / math.sqrt(1 - _E2 * math.sin(p1) ** 2)
    t1, c1 = math.tan(p1) ** 2, _EP2 * math.cos(p1) ** 2
    r1 = _A * (1 - _E2) / (1 - _E2 * math.sin(p1) ** 2) ** 1.5
    d = x / (n1 * _K0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * _EP2) * d ** 4 / 24
                                           + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * _EP2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * _EP2 + 24 * t1 * t1) * d ** 5 / 120) / math.cos(p1)
    return math.degrees(lat), zone * 6 - 183 + math.degrees(lon)
