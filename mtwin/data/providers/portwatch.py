"""IMF PortWatch provider (daily chokepoint transit counts via the ArcGIS REST API).

Data: IMF PortWatch / UN Global Platform. The recommended citation is
"Sources: UN Global Platform; IMF PortWatch (portwatch.imf.org)". Terms of use:
https://www.imf.org/external/terms.htm
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import pandas as pd

from mtwin.data.errors import ProviderError
from mtwin.data.http import HttpClient

CHOKEPOINTS_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
    "Daily_Chokepoints_Data/FeatureServer/0/query"
)
PAGE_SIZE = 1000  # the layer's maximum record count per request
NUMERIC_FIELDS = ["n_tanker", "n_total", "n_container", "n_dry_bulk", "n_general_cargo", "n_roro"]
COLUMNS = ["date", "portid", "portname", *NUMERIC_FIELDS]
CITATION = "Sources: UN Global Platform; IMF PortWatch (portwatch.imf.org)."


def parse_portwatch(payload: Any) -> pd.DataFrame:
    """Convert an ArcGIS ``query`` response into a tidy frame.

    The ``date`` attribute is an ISO string (``esriFieldTypeDateOnly``) in the current schema
    and epoch milliseconds in older ones; both are accepted.
    """
    if not isinstance(payload, dict):
        raise ProviderError("PortWatch returned an unexpected payload")
    if "error" in payload:
        raise ProviderError("PortWatch API reported an error for this request")
    rows = [feature.get("attributes", {}) for feature in payload.get("features", [])]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    if pd.api.types.is_numeric_dtype(frame["date"]):
        frame["date"] = pd.to_datetime(frame["date"], unit="ms")
    else:
        frame["date"] = pd.to_datetime(frame["date"])
    for col in NUMERIC_FIELDS:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    present = [col for col in COLUMNS if col in frame.columns]
    return frame[present]


class PortWatchProvider:
    """Download daily transit counts for named chokepoints."""

    name = "IMF PortWatch"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def fetch_chokepoints(
        self, names: Sequence[str], start: date, max_rows_per_name: int = 3000
    ) -> pd.DataFrame:
        """Fetch daily rows for each chokepoint from ``start`` to the latest available date."""
        frames = [self._fetch_one(name, start, max_rows_per_name) for name in names]
        result = pd.concat(frames, ignore_index=True)
        if result.empty:
            raise ProviderError("PortWatch returned no chokepoint data")
        result = result.drop_duplicates(["portname", "date"]).sort_values(["portname", "date"])
        return result.reset_index(drop=True)

    def _fetch_one(self, name: str, start: date, max_rows: int) -> pd.DataFrame:
        escaped = name.replace("'", "''")
        pages: list[pd.DataFrame] = []
        offset = 0
        start_ts = pd.Timestamp(start)
        while offset < max_rows:
            payload = self._http.get_json(
                CHOKEPOINTS_URL,
                {
                    "where": f"portname='{escaped}'",
                    "outFields": ",".join(COLUMNS),
                    "orderByFields": "date DESC",
                    "resultOffset": offset,
                    "resultRecordCount": PAGE_SIZE,
                    "returnGeometry": "false",
                    "f": "json",
                },
            )
            page = parse_portwatch(payload)
            if page.empty:
                break
            pages.append(page)
            if len(page) < PAGE_SIZE or page["date"].min() <= start_ts:
                break
            offset += PAGE_SIZE
        if not pages:
            raise ProviderError(f"PortWatch has no rows for chokepoint '{name}'")
        frame = pd.concat(pages, ignore_index=True)
        return frame[frame["date"] >= start_ts]
