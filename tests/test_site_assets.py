"""Landing-page asset scripts: GSAP vendoring and the map projection."""

from __future__ import annotations

import io
import re
import tarfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

from scripts import build_site_map_fonts as geo
from scripts import vendor_gsap

SITE = Path(__file__).resolve().parents[1] / "site"


def _tarball(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def test_integrity_matches_the_known_sha512_of_empty_input():
    expected = "sha512-z4PhNX7vuL3xVChQ1m2AB9Yg5AULVxXcg/SpIdNs6c5H0NE8XYXysP+DGNKHfuwvY7kxvUdBeoGlODJ6+SfaPg=="
    assert vendor_gsap.integrity(b"") == expected


def test_verify_rejects_a_tampered_tarball():
    with pytest.raises(ValueError, match="integrity mismatch"):
        vendor_gsap.verify(b"not the real release")


def test_pinned_release_is_3_15_0_from_the_npm_registry():
    assert vendor_gsap.URL == "https://registry.npmjs.org/gsap/-/gsap-3.15.0.tgz"
    assert vendor_gsap.INTEGRITY.startswith("sha512-")


def test_extract_writes_only_the_listed_files(tmp_path):
    data = _tarball(
        {
            "package/dist/gsap.min.js": b"core",
            "package/dist/ScrollTrigger.min.js": b"st",
            "package/../../evil.js": b"x",
            "package/dist/Draggable.min.js": b"unused",
        }
    )
    written = vendor_gsap.extract(data, tmp_path / "gsap")
    assert sorted(p.name for p in written) == ["ScrollTrigger.min.js", "gsap.min.js"]
    assert (tmp_path / "gsap" / "gsap.min.js").read_bytes() == b"core"
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == [
        "ScrollTrigger.min.js",
        "gsap.min.js",
    ]


def test_extract_fails_when_the_release_layout_changes(tmp_path):
    with pytest.raises(KeyError):
        vendor_gsap.extract(_tarball({"package/gsap.js": b"core"}), tmp_path)


def test_equal_earth_hand_computed_points():
    assert geo.equal_earth(0.0, 0.0) == (0.0, 0.0)
    # x = 2*sqrt(3)*pi / (3*A1) at the equator on the antimeridian = 2.70664, times SCALE.
    assert geo.equal_earth(180.0, 0.0) == (541.3, 0.0)
    assert geo.equal_earth(-180.0, 0.0) == (-541.3, 0.0)
    x, y = geo.equal_earth(30.0, 45.0)
    assert x > 0 and y < 0  # east and north (SVG y points down)


class _AppLinks(HTMLParser):
    """Collect the attributes of every ``<a data-app-link>``."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag == "a" and "data-app-link" in found:
            self.links.append(found)


def test_launch_links_in_the_html_match_the_configured_app_url():
    config = (SITE / "js" / "config.js").read_text(encoding="utf-8")
    match = re.search(r'appUrl:\s*"([^"]+)"', config)
    assert match, "appUrl is not set in site/js/config.js"
    parser = _AppLinks()
    parser.feed((SITE / "index.html").read_text(encoding="utf-8"))
    assert len(parser.links) == 3  # hero, section 5, footer
    for link in parser.links:
        assert link["href"] == match.group(1)
        assert link["target"] == "_blank"
        assert link["rel"] == "noopener noreferrer"
        assert link.get("aria-label")
