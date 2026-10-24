"""Download every dataset once and report where each came from.

Usage::

    python scripts/fetch_data.py                # fill the local cache
    python scripts/fetch_data.py --force        # ignore fresh cache entries
    python scripts/fetch_data.py --snapshot     # also write committed-friendly snapshots

Exit code 0 when every dataset is real, 1 when any fell back to synthetic data.
"""

from __future__ import annotations

import argparse
import logging
import sys

from mtwin.config import load_settings
from mtwin.data import DataService
from mtwin.data.service import LoadResult


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--force", action="store_true", help="bypass fresh cache entries")
    parser.add_argument(
        "--snapshot", action="store_true", help="write snapshots to the snapshot directory"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s"
    )

    settings = load_settings()
    service = DataService(settings)
    results: dict[str, LoadResult] = {
        "prices": service.prices(refresh=args.force),
        "chokepoints": service.chokepoints(refresh=args.force),
        "macro": service.macro(refresh=args.force),
    }
    failed = False
    for name, res in results.items():
        print(f"{name:<12} {res.source:<12} rows={len(res.data):>7}  {res.label}")
        for note in res.notes:
            print(f"             note: {note}")
        if not res.is_real:
            failed = True
        elif args.snapshot:
            service.write_snapshot(res)
            print(f"             snapshot written to {settings.snapshot_dir}")
    if failed:
        print("\nSome datasets fell back to synthetic data (see notes above).", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
