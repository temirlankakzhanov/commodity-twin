"""Build the landing page's static assets: the projected map and subset web fonts.

Inputs are downloaded once by hand (not by this script) and passed as paths:

* Natural Earth 1:110m land, GeoJSON (public domain).
* Inter variable TTF and JetBrains Mono Regular TTF (SIL Open Font License 1.1).

Outputs: ``site/data/geo.json`` (land outline, illustrative route lines, port and chokepoint
positions in Equal Earth coordinates) and ``site/fonts/*.woff``. Route waypoints are
illustrative sea lanes drawn for the demonstration network; they are not vessel tracks.

Usage::

    python scripts/build_site_map_fonts.py --land ne_110m_land.geojson \
        --inter InterVariable.ttf --mono JetBrainsMono-Regular.ttf
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

# Equal Earth projection (Šavrič, Patterson and Jenny, 2018), central meridian 0.
A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
SCALE = 200.0
EXTENT = {"lon": (-104.0, 146.0), "lat": (-56.0, 72.0)}  # map window shown on wide screens
EXTENT_NARROW = {"lon": (8.0, 124.0), "lat": (-38.0, 50.0)}  # phones: Gulf to Malacca
MIN_STEP = 0.35  # drop vertices closer than this (projected units) to the previous one

PORTS = {
    "Houston": (-94.9, 29.3),
    "Ras Tanura": (50.2, 26.7),
    "Novorossiysk (CPC)": (37.8, 44.7),
    "Rotterdam": (4.1, 51.95),
    "Ningbo": (121.9, 29.9),
    "Sikka (India)": (69.8, 22.4),
}
CHOKEPOINTS = {
    "Strait of Hormuz": (56.4, 26.5),
    "Bab el-Mandeb Strait": (43.4, 12.6),
    "Suez Canal": (32.5, 30.0),
    "Malacca Strait": (100.3, 3.2),
    "Panama Canal": (-79.6, 9.1),
    "Cape of Good Hope": (18.5, -34.8),
}

# Shared sea-lane segments (lon, lat), drawn by hand to stay off land at this scale.
_GULF_TO_ATLANTIC = [(-94.9, 29.3), (-90.0, 26.0), (-84.5, 24.3), (-81.0, 24.1), (-79.9, 25.0)]
_GULF_TO_ATLANTIC += [(-79.8, 27.6)]
_CHANNEL = [(-12.0, 46.5), (-6.0, 48.8), (-1.0, 50.1), (1.6, 50.9), (3.4, 51.7), (4.1, 51.95)]
_ATLANTIC_SOUTH = [(-74.0, 28.0), (-45.0, 8.0), (-25.0, -12.0), (2.0, -32.0), (18.5, -36.5)]
_INDIAN_SOUTH = [(18.5, -36.5), (40.0, -37.0), (75.0, -12.0), (94.0, 6.6)]
_MALACCA_TO_NINGBO = [
    (94.0, 6.6),
    (97.8, 5.6),
    (99.6, 3.9),
    (100.3, 3.2),
    (101.4, 2.5),
    (103.4, 1.0),
    (104.6, 1.1),
    (105.5, 2.2),
    (109.0, 7.0),
    (115.5, 16.5),
    (119.8, 23.5),
    (122.6, 28.5),
    (121.9, 29.9),
]
_GULF_EXIT = [(50.2, 26.7), (51.5, 26.9), (53.0, 26.3), (55.0, 26.2), (56.4, 26.5), (57.2, 25.3)]
_GULF_EXIT += [(61.0, 22.7)]
_RED_SEA_NORTH = [
    (43.4, 12.6),
    (40.5, 16.0),
    (37.5, 21.5),
    (34.0, 27.4),
    (33.2, 28.4),
    (32.6, 29.6),
    (32.5, 30.0),
    (32.3, 31.4),
]
_MED_WEST = [(28.0, 33.6), (19.0, 34.6), (11.5, 37.4), (2.0, 37.3), (-5.6, 35.95), (-9.6, 36.4)]
_IBERIA_TO_CHANNEL = [(-9.6, 36.4), (-10.3, 43.0), *_CHANNEL]
_BLACK_SEA_OUT = [(37.8, 44.7), (33.0, 43.2), (29.1, 41.3), (26.3, 40.1), (25.5, 37.5)]

ROUTES: dict[str, list[list[tuple[float, float]]]] = {
    "Houston-Rotterdam": [[*_GULF_TO_ATLANTIC, (-70.0, 35.0), (-40.0, 45.0), *_CHANNEL]],
    "Houston-Ningbo via Cape": [
        [*_GULF_TO_ATLANTIC, *_ATLANTIC_SOUTH, *_INDIAN_SOUTH[1:], *_MALACCA_TO_NINGBO[1:]]
    ],
    "Houston-Ningbo via Panama": [
        [
            (-94.9, 29.3),
            (-89.0, 24.0),
            (-86.0, 21.0),
            (-80.5, 12.5),
            (-79.6, 9.1),
            (-79.4, 8.4),
            (-79.3, 6.8),
            (-83.0, 6.3),
            (-92.0, 9.0),
            (-120.0, 17.0),
        ],
        [(160.0, 30.0), (132.0, 30.0), (124.0, 29.8), (121.9, 29.9)],
    ],
    "Houston-Sikka via Cape": [
        [
            *_GULF_TO_ATLANTIC,
            *_ATLANTIC_SOUTH,
            (40.0, -37.0),
            (55.0, -25.0),
            (62.0, 5.0),
            (67.5, 20.5),
            (69.8, 22.4),
        ]
    ],
    "Ras Tanura-Ningbo": [
        [*_GULF_EXIT, (66.0, 17.0), (78.0, 5.0), (81.0, 5.0), *_MALACCA_TO_NINGBO]
    ],
    "Ras Tanura-Sikka": [[*_GULF_EXIT[:6], (61.0, 24.4), (66.0, 23.5), (69.8, 22.4)]],
    "Ras Tanura-Rotterdam via Suez": [
        [
            *_GULF_EXIT,
            (58.6, 18.0),
            (51.5, 13.2),
            *_RED_SEA_NORTH,
            *_MED_WEST,
            *_IBERIA_TO_CHANNEL[1:],
        ]
    ],
    "Ras Tanura-Rotterdam via Cape": [
        [
            *_GULF_EXIT,
            (53.0, 5.0),
            (42.5, -15.0),
            (35.0, -31.0),
            (18.5, -36.5),
            (4.0, -20.0),
            (-18.0, 8.0),
            (-22.0, 20.0),
            (-21.0, 28.0),
            *_CHANNEL,
        ]
    ],
    "CPC-Rotterdam": [
        [
            *_BLACK_SEA_OUT,
            (24.5, 35.9),
            (21.0, 35.3),
            (15.0, 35.8),
            *_MED_WEST[2:],
            *_IBERIA_TO_CHANNEL[1:],
        ]
    ],
    "CPC-Ningbo via Suez": [
        [
            *_BLACK_SEA_OUT,
            (28.0, 33.6),
            *reversed(_RED_SEA_NORTH),
            (51.5, 13.2),
            (66.0, 10.0),
            (78.0, 5.0),
            (81.0, 5.0),
            *_MALACCA_TO_NINGBO,
        ]
    ],
}

FONT_UNICODES = [
    *range(0x20, 0x7F),
    *range(0xA0, 0x100),
    *range(0x2010, 0x2028),
    *range(0x2030, 0x203B),
    0x2122,
    *range(0x2190, 0x2194),
    0x2212,
    0x2248,
    0x2264,
    0x2265,
]


def equal_earth(lon: float, lat: float) -> tuple[float, float]:
    """Project degrees to Equal Earth coordinates, scaled by ``SCALE``, y pointing down."""
    lam, phi = math.radians(lon), math.radians(lat)
    theta = math.asin(math.sqrt(3.0) / 2.0 * math.sin(phi))
    t2, t6 = theta * theta, theta**6
    x = 2.0 * math.sqrt(3.0) * lam * math.cos(theta)
    x /= 3.0 * (A1 + 3.0 * A2 * t2 + t6 * (7.0 * A3 + 9.0 * A4 * t2))
    y = theta * (A1 + A2 * t2 + t6 * (A3 + A4 * t2))
    return round(x * SCALE, 1), round(-y * SCALE, 1)


def path_d(lines: Iterable[Sequence[tuple[float, float]]], *, close: bool) -> str:
    """SVG path data for projected polylines, thinning vertices closer than ``MIN_STEP``."""
    parts = []
    for line in lines:
        pts = [equal_earth(lon, lat) for lon, lat in line]
        kept = [pts[0]]
        for p in pts[1:]:
            if math.hypot(p[0] - kept[-1][0], p[1] - kept[-1][1]) >= MIN_STEP:
                kept.append(p)
        if close and len(kept) < 3:
            continue
        cmd = "M" + "L".join(f"{x:g} {y:g}" for x, y in kept)
        parts.append(cmd + ("Z" if close else ""))
    return "".join(parts)


def land_rings(geojson: dict) -> list[list[tuple[float, float]]]:
    """Outer and inner rings of every land polygon, Antarctica excluded."""
    rings = []
    for feature in geojson["features"]:
        geom = feature["geometry"]
        polygons = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for polygon in polygons:
            if max(lat for _, lat in polygon[0]) < -60.0:
                continue
            rings.extend([[(lon, lat) for lon, lat in ring] for ring in polygon])
    return rings


def view_box(extent: dict[str, tuple[float, float]]) -> list[float]:
    """``[x, y, width, height]`` of a map window in projected coordinates."""
    (lon0, lon1), (lat0, lat1) = extent["lon"], extent["lat"]
    corners = [equal_earth(lon, lat) for lon in (lon0, lon1) for lat in (lat0, lat1, 0.0)]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    return [min(xs), min(ys), round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1)]


def build_geo(land_geojson: dict) -> dict:
    """The map payload consumed by ``site/js``."""
    return {
        "projection": "Equal Earth, central meridian 0",
        "viewBox": view_box(EXTENT),
        "viewBoxNarrow": view_box(EXTENT_NARROW),
        "land": path_d(land_rings(land_geojson), close=True),
        "routes": {name: path_d(lines, close=False) for name, lines in ROUTES.items()},
        "ports": {name: equal_earth(*ll) for name, ll in PORTS.items()},
        "chokepoints": {name: equal_earth(*ll) for name, ll in CHOKEPOINTS.items()},
        "note": "Route lines are illustrative sea lanes for the demonstration network.",
        "source": "Made with Natural Earth (public domain), 1:110m land.",
    }


def subset_font(src: Path, dest: Path, weight: float | None = None) -> None:
    """Latin subset as WOFF; pin a variable font to one ``weight`` when given."""
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    font = TTFont(src)
    if weight is not None:
        font = instancer.instantiateVariableFont(font, {"wght": weight, "opsz": None})
    options = subset.Options()
    options.flavor = "woff"
    options.layout_features = ["kern", "liga", "calt", "tnum", "case"]
    options.name_IDs = ["*"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=FONT_UNICODES)
    subsetter.subset(font)
    dest.parent.mkdir(parents=True, exist_ok=True)
    font.flavor = "woff"
    font.save(dest)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--land", type=Path, required=True)
    parser.add_argument("--inter", type=Path)
    parser.add_argument("--mono", type=Path)
    args = parser.parse_args(argv)

    geo = build_geo(json.loads(args.land.read_text(encoding="utf-8")))
    out = SITE / "data" / "geo.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(geo, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size / 1024:.0f} KB)")
    fonts = SITE / "fonts"
    if args.inter:
        for weight in (400, 600):
            subset_font(args.inter, fonts / f"inter-{weight}.woff", weight)
    if args.mono:
        subset_font(args.mono, fonts / "jetbrains-mono-400.woff")
    for path in sorted(fonts.glob("*.woff")):
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
