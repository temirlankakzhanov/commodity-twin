"""Verify the pinned GSAP release and unpack the two files the landing page loads.

GSAP is not committed: it is distributed under GreenSock's standard "no charge" licence
(https://gsap.com/community/standard-license/), not an open-source licence.
``make site-assets`` (locally) and the Pages workflow (at deploy) download the tarball with curl
and pass it to this script, which refuses it unless its SHA-512 matches the npm registry
integrity pinned below.

Usage::

    python scripts/vendor_gsap.py --url              # print the tarball URL
    python scripts/vendor_gsap.py FILE.tgz           # verify, then write site/vendor/gsap/
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import tarfile
from collections.abc import Mapping
from pathlib import Path

VERSION = "3.15.0"
URL = f"https://registry.npmjs.org/gsap/-/gsap-{VERSION}.tgz"
# ``npm view gsap@3.15.0 dist.integrity``
INTEGRITY = (
    "sha512-dMW4CWBTUK1AEEDeZc1g4xpPGIrSf9fJF960qbTZmN/QwZIWY5w"
    "gliS6JWl9/25fpTGJrMRtSjGtOmPnfjZB+A=="
)
FILES = {
    "package/dist/gsap.min.js": "gsap.min.js",
    "package/dist/ScrollTrigger.min.js": "ScrollTrigger.min.js",
}
DEST = Path(__file__).resolve().parents[1] / "site" / "vendor" / "gsap"


def integrity(data: bytes) -> str:
    """Subresource-integrity style digest, as npm reports it: ``sha512-<base64>``."""
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")


def verify(data: bytes, expected: str = INTEGRITY) -> None:
    """Raise ``ValueError`` unless ``data`` has the expected integrity."""
    actual = integrity(data)
    if actual != expected:
        raise ValueError(f"GSAP tarball integrity mismatch: got {actual}, expected {expected}")


def extract(data: bytes, dest: Path, files: Mapping[str, str] = FILES) -> list[Path]:
    """Write only the listed regular files from the tarball into ``dest`` (no ``extractall``)."""
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member_name, target in files.items():
            member = archive.getmember(member_name)  # KeyError if the release layout changed
            if not member.isfile():
                raise ValueError(f"{member_name} is not a regular file")
            source = archive.extractfile(member)
            assert source is not None
            path = dest / target
            path.write_bytes(source.read())
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tarball", type=Path, nargs="?")
    parser.add_argument("--url", action="store_true", help="print the pinned tarball URL")
    parser.add_argument("--dest", type=Path, default=DEST)
    args = parser.parse_args(argv)
    if args.url:
        print(URL)
        return
    if args.tarball is None:
        parser.error("pass the downloaded tarball, or --url")
    data = args.tarball.read_bytes()
    verify(data)
    for path in extract(data, args.dest):
        print(f"GSAP {VERSION}: {path} ({path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
