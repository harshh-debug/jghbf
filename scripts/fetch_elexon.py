#!/usr/bin/env python3
"""Fetch authentic challenge data with stdlib only; never fabricate on failure."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://data.elexon.co.uk/bmrs/api/v1"


def fetch(item: tuple[str, str, dict]) -> dict:
    filename, endpoint, params = item
    url = BASE + endpoint + "?" + urllib.parse.urlencode(params)
    error = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read()
                status = response.status
                headers = {k: response.headers[k] for k in
                           ("Content-Type", "Date", "ETag", "Last-Modified") if k in response.headers}
            rows = json.loads(payload)
            if not isinstance(rows, list) or not rows:
                raise ValueError("Expected a non-empty stream JSON array; refusing silent fallback")
            if not all(isinstance(r, dict) and "generation" in r and "startTime" in r for r in rows):
                raise ValueError("Unexpected stream row shape")
            if "FUELHH" in endpoint and any(r.get("fuelType") != "WIND" for r in rows):
                raise ValueError("Upstream did not respect WIND filter")
            target = ROOT / "data/raw" / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            return {"path": str(target.relative_to(ROOT)), "url": url, "http_status": status,
                    "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "response_headers": headers, "bytes": len(payload), "rows": len(rows),
                    "sha256": hashlib.sha256(payload).hexdigest(), "parameters": params}
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            error = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    raise RuntimeError(f"Failed to fetch {url}: {error}")


def main() -> None:
    boundaries = ["2025-12-30", "2026-01-06", "2026-01-13", "2026-01-20", "2026-01-27", "2026-02-01"]
    jobs = []
    for start, end in zip(boundaries, boundaries[1:]):
        jobs.append((f"windfor_{start}_{end}.json", "/datasets/WINDFOR/stream",
                     {"publishDateTimeFrom": start + "T00:00:00Z", "publishDateTimeTo": end + "T00:00:00Z"}))
    jobs.append(("fuelhh_wind_2026-01-01_2026-02-01.json", "/datasets/FUELHH/stream",
                 {"settlementDateFrom": "2026-01-01", "settlementDateTo": "2026-02-01", "fuelType": "WIND"}))
    # Small bounded parallelism for independent read-only public requests.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(fetch, jobs))
    manifest = {"description": "Unmodified Elexon stream response bodies. WINDFOR requests filter publication time, not target time.",
                "scope": {"decision_dates": ["2026-01-01", "2026-01-31"],
                          "delivery_dates": ["2026-01-02", "2026-02-01"],
                          "buffer_actual_date": "2026-01-01", "forecast_publication_buffer_from": "2025-12-30"},
                "boundary_policy": "Upstream inclusion is not assumed. Deduplicate exact overlaps and filter locally to explicit half-open windows.",
                "requests": results}
    (ROOT / "data/manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps([{k: r[k] for k in ("path", "rows", "bytes")} for r in results], indent=2))


if __name__ == "__main__":
    main()
