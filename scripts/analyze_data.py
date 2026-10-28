#!/usr/bin/env python3
"""Reproducible reference analysis, not an application or a trading model.

Hourly alignment is an explicit pilot convention: forecast at h is compared
with the mean of actual MW at h and h+30m. See context/methodology.md.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc
LONDON = ZoneInfo("Europe/London")


def timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Naive timestamps are not allowed")
    return parsed.astimezone(UTC)


def iso(value: dt.datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def cutoff_for(day: dt.date, hhmm: str) -> dt.datetime:
    parsed = dt.time.fromisoformat(hhmm)
    if len(hhmm) != 5 or parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise ValueError("Cutoff must be HH:MM, 00:00 through 23:59")
    return dt.datetime.combine(day, parsed, LONDON).astimezone(UTC)


def deduplicate(rows: list[dict], kind: str) -> tuple[list[dict], int]:
    values = {}
    duplicates = 0
    for row in rows:
        if row.get("dataset") != kind:
            raise ValueError(f"Unexpected dataset: {row.get('dataset')}")
        if kind == "FUELHH" and row.get("fuelType") != "WIND":
            raise ValueError("Actuals contain a non-WIND row")
        timestamp(row["startTime"])
        timestamp(row["publishTime"])
        value = row.get("generation")
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError("generation must be finite numeric MW or null")
        key = (row["startTime"], row["publishTime"])
        if key in values:
            if values[key].get("generation") != value:
                raise ValueError(f"Conflicting duplicate in {kind}: {key}")
            duplicates += 1
        else:
            values[key] = row
    return sorted(values.values(), key=lambda r: (r["startTime"], r["publishTime"])), duplicates


def select_forecast(vintages: list[dict], cutoff: dt.datetime) -> dict | None:
    # A latest null revision remains null: do not silently choose an older value.
    eligible = [row for row in vintages if timestamp(row["publishTime"]) <= cutoff]
    return max(eligible, key=lambda r: timestamp(r["publishTime"])) if eligible else None


def metrics(points: list[dict]) -> dict:
    errors = [p["error_mw"] for p in points if p["error_mw"] is not None]
    if not errors:
        return {"matched_hours": 0, "mae_mw": None, "rmse_mw": None, "bias_mw": None}
    n = len(errors)
    return {"matched_hours": n, "mae_mw": sum(abs(x) for x in errors) / n,
            "rmse_mw": math.sqrt(sum(x*x for x in errors) / n), "bias_mw": sum(errors) / n}


def comparison(wind: list[dict], actual: list[dict], hhmm: str) -> list[dict]:
    by_target = defaultdict(list)
    for row in wind:
        by_target[timestamp(row["startTime"])].append(row)
    outturn = {}
    for row in actual:
        target = timestamp(row["startTime"])
        old = outturn.get(target)
        if old is None or timestamp(row["publishTime"]) > timestamp(old["publishTime"]):
            outturn[target] = row
    points = []
    for number in range(31):
        decision_day = dt.date(2026, 1, 1) + dt.timedelta(days=number)
        cutoff = cutoff_for(decision_day, hhmm)
        delivery_day = decision_day + dt.timedelta(days=1)
        start = dt.datetime.combine(delivery_day, dt.time(), LONDON).astimezone(UTC)
        for hour in range(24):  # January scope only: no DST transition in these delivery dates.
            target = start + dt.timedelta(hours=hour)
            chosen = select_forecast(by_target.get(target, []), cutoff)
            forecast = chosen.get("generation") if chosen else None
            halves = [outturn.get(target + dt.timedelta(minutes=m)) for m in (0, 30)]
            valid_actual = all(r is not None and r.get("generation") is not None for r in halves)
            actual_mw = sum(r["generation"] for r in halves) / 2 if valid_actual else None
            reasons = []
            if chosen is None:
                reasons.append("no_forecast_by_cutoff")
            elif forecast is None:
                reasons.append("null_forecast")
            if not valid_actual:
                reasons.append("missing_or_null_actual_half_hour")
            points.append({"decision_date": str(decision_day), "delivery_date": str(delivery_day),
                           "cutoff_utc": iso(cutoff), "start_time": iso(target),
                           "publish_time": chosen["publishTime"] if chosen else None,
                           "forecast_mw": forecast, "actual_hourly_mean_mw": actual_mw,
                           "error_mw": forecast - actual_mw if forecast is not None and actual_mw is not None else None,
                           "missing_reason": ";".join(reasons)})
    return points


def csv_file(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff", default="09:00", help="Pilot assumption in Europe/London, not a verified market gate")
    args = parser.parse_args()
    cutoff_for(dt.date(2026, 1, 1), args.cutoff)
    manifest = json.loads((ROOT / "data/manifest.json").read_text())
    raw = defaultdict(list)
    for request in manifest["requests"]:
        payload = (ROOT / request["path"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != request["sha256"]:
            raise ValueError(f"Checksum mismatch: {request['path']}")
        rows = json.loads(payload)
        if len(rows) != request["rows"]:
            raise ValueError("Manifest row count mismatch")
        raw[rows[0]["dataset"]].extend(rows)
    wind, wind_duplicates = deduplicate(raw["WINDFOR"], "WINDFOR")
    actual, actual_duplicates = deduplicate(raw["FUELHH"], "FUELHH")
    points = comparison(wind, actual, args.cutoff)
    assert len(points) == 744
    assert all(p["publish_time"] is None or timestamp(p["publish_time"]) <= timestamp(p["cutoff_utc"]) for p in points)
    daily = []
    for day in sorted({p["decision_date"] for p in points}):
        rows = [p for p in points if p["decision_date"] == day]
        daily.append({"decision_date": day, "delivery_date": rows[0]["delivery_date"],
                      "expected_hours": 24, **metrics(rows)})
    publications = sorted({r["publishTime"] for r in wind})
    targets = sorted({r["startTime"] for r in wind})
    default_output = ROOT / "data/derived" if args.cutoff == "09:00" else ROOT / "data/derived" / args.cutoff.replace(":", "")
    default_output.mkdir(parents=True, exist_ok=True)
    report = {"generated_at_utc": dt.datetime.now(UTC).isoformat(),
              "cutoff_local": args.cutoff, "timezone": "Europe/London", "cutoff_is_assumption": True,
              "alignment": "forecast[h] versus (actual[h]+actual[h+30min])/2; explicit pilot convention",
              "bias_sign": "forecast minus actual: positive means wind overforecast",
              "window": {"decisions": ["2026-01-01", "2026-01-31"], "deliveries": ["2026-01-02", "2026-02-01"]},
              "raw_rows": {k: len(v) for k,v in raw.items()},
              "unique_rows": {"WINDFOR": len(wind), "FUELHH_WIND": len(actual)},
              "duplicates_removed": {"WINDFOR": wind_duplicates, "FUELHH_WIND": actual_duplicates},
              "null_generation_rows": {"WINDFOR": sum(r.get("generation") is None for r in wind),
                                       "FUELHH_WIND": sum(r.get("generation") is None for r in actual)},
              "forecast_publications": {"count": len(publications), "first": publications[0], "last": publications[-1],
                                        "observed_utc_clock_times": sorted({timestamp(v).strftime("%H:%M:%S") for v in publications}),
                                        "per_publication_target_counts": dict(Counter(Counter(r["publishTime"] for r in wind).values()))},
              "forecast_targets": {"first": targets[0], "last": targets[-1],
                                   "observed_minutes": sorted({timestamp(v).minute for v in targets})},
              "actual_targets": {"first": min(r["startTime"] for r in actual), "last": max(r["startTime"] for r in actual),
                                 "unique_target_count": len({r["startTime"] for r in actual}),
                                 "observed_minutes": sorted({timestamp(r["startTime"]).minute for r in actual})},
              "comparison": {"expected_hours": len(points), **metrics(points),
                             "missing_reason_counts": dict(Counter(p["missing_reason"] for p in points if p["missing_reason"]))},
              "daily": daily}
    (default_output / "quality-report.json").write_text(json.dumps(report, indent=2) + "\n")
    csv_file(default_output / "comparison-hourly.csv", points)
    csv_file(default_output / "daily-metrics.csv", daily)
    if args.cutoff == "09:00":
        csv_file(default_output / "windfor-normalized.csv", [{"start_time": r["startTime"], "publish_time": r["publishTime"], "generation_mw": r["generation"]} for r in wind])
        csv_file(default_output / "actual-wind-normalized.csv", [{"start_time": r["startTime"], "publish_time": r["publishTime"], "generation_mw": r["generation"]} for r in actual])
        # A small real API-derived example for contract discussions. Values are not invented.
        example = {"status": "reference_analysis_not_live_api", "decision_date": "2026-01-15", "cutoff_local": args.cutoff,
                   "timezone": "Europe/London", "series": [p for p in points if p["decision_date"] == "2026-01-15"]}
        (ROOT / "evidence/real-day-example.json").write_text(json.dumps(example, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("unique_rows", "duplicates_removed", "forecast_publications", "comparison")}, indent=2))


if __name__ == "__main__":
    main()
