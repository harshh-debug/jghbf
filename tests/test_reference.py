"""Hypothetical unit cases plus checks against downloaded real data.

Synthetic numbers exist only in these unit tests, never in the dashboard data.
"""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reference", ROOT / "scripts/analyze_data.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def forecast(publication, generation, target="2026-01-02T00:00:00Z"):
    return {"dataset": "WINDFOR", "startTime": target,
            "publishTime": publication, "generation": generation}


def actual(target, generation):
    return {"dataset": "FUELHH", "fuelType": "WIND", "startTime": target,
            "publishTime": "2026-01-03T00:00:00Z", "generation": generation}


class ReferenceTests(unittest.TestCase):
    def test_latest_eligible_excludes_future_includes_equality(self):
        rows = [forecast("2026-01-01T09:00:00Z", 100),
                forecast("2026-01-01T10:00:00Z", 200),
                forecast("2026-01-01T10:01:00Z", 999)]
        self.assertEqual(ref.select_forecast(rows, ref.timestamp("2026-01-01T10:00:00Z"))["generation"], 200)

    def test_missing_eligible_forecast_is_missing(self):
        row = forecast("2026-01-01T11:00:00Z", 999)
        self.assertIsNone(ref.select_forecast([row], ref.timestamp("2026-01-01T10:00:00Z")))

    def test_selection_does_not_carry_forecasts_between_targets(self):
        rows = [forecast("2026-01-01T08:00:00Z", 80),
                forecast("2026-01-01T10:00:00Z", 999, "2026-01-02T01:00:00Z")]
        points = ref.comparison(rows, [], "09:00")
        self.assertEqual(points[0]["forecast_mw"], 80)
        self.assertIsNone(points[1]["forecast_mw"])

    def test_zero_is_valid_not_missing(self):
        point = ref.comparison([forecast("2026-01-01T08:00:00Z", 0)],
                               [actual("2026-01-02T00:00:00Z", 0), actual("2026-01-02T00:30:00Z", 0)], "09:00")[0]
        self.assertEqual(point["error_mw"], 0)
        self.assertEqual(ref.metrics([point])["matched_hours"], 1)

    def test_latest_null_does_not_fallback_to_older_value(self):
        rows = [forecast("2026-01-01T09:00:00Z", 100), forecast("2026-01-01T09:30:00Z", None)]
        self.assertIsNone(ref.select_forecast(rows, ref.timestamp("2026-01-01T10:00:00Z"))["generation"])

    def test_hourly_actuals_use_both_half_hours(self):
        rows = [actual("2026-01-02T00:00:00Z", 80), actual("2026-01-02T00:30:00Z", 120)]
        point = ref.comparison([forecast("2026-01-01T09:30:00Z", 130)], rows, "10:00")[0]
        self.assertEqual(point["actual_hourly_mean_mw"], 100)
        self.assertEqual(point["error_mw"], 30)

    def test_missing_half_hour_is_not_zero_or_partial_mean(self):
        point = ref.comparison([forecast("2026-01-01T09:30:00Z", 100)],
                               [actual("2026-01-02T00:00:00Z", 80)], "10:00")[0]
        self.assertIsNone(point["actual_hourly_mean_mw"])
        self.assertIsNone(point["error_mw"])

    def test_latest_actual_revision_is_used_for_retrospective_truth(self):
        old = actual("2026-01-02T00:00:00Z", 40)
        new = {**old, "publishTime": "2026-01-04T00:00:00Z", "generation": 80}
        point = ref.comparison([], [old, new, actual("2026-01-02T00:30:00Z", 120)], "10:00")[0]
        self.assertEqual(point["actual_hourly_mean_mw"], 100)

    def test_metrics_sign_missing_and_empty(self):
        m = ref.metrics([{"error_mw": 3}, {"error_mw": -4}, {"error_mw": None}])
        self.assertEqual(m["matched_hours"], 2)
        self.assertEqual(m["mae_mw"], 3.5)
        self.assertAlmostEqual(m["rmse_mw"], (12.5)**0.5)
        self.assertEqual(m["bias_mw"], -0.5)
        self.assertIsNone(ref.metrics([])["mae_mw"])

    def test_duplicate_conflicts_raise(self):
        first = forecast("2026-01-01T09:30:00Z", 100)
        rows, count = ref.deduplicate([first, first], "WINDFOR")
        self.assertEqual((len(rows), count), (1, 1))
        with self.assertRaises(ValueError):
            ref.deduplicate([first, {**first, "generation": 200}], "WINDFOR")

    def test_january_boundaries(self):
        points = ref.comparison([], [], "10:00")
        self.assertEqual(len(points), 744)
        self.assertEqual(points[0]["decision_date"], "2026-01-01")
        self.assertEqual(points[0]["start_time"], "2026-01-02T00:00:00Z")
        self.assertEqual(points[-1]["decision_date"], "2026-01-31")
        self.assertEqual(points[-1]["start_time"], "2026-02-01T23:00:00Z")

    def test_timezone_and_cutoff_validation(self):
        self.assertEqual(ref.iso(ref.cutoff_for(dt.date(2026, 1, 1), "10:00")), "2026-01-01T10:00:00Z")
        # Helper is timezone-aware; comparison's fixed 24-hour loop is January-specific.
        self.assertEqual(ref.iso(ref.cutoff_for(dt.date(2026, 7, 1), "10:00")), "2026-07-01T09:00:00Z")
        for value in ["25:00", "10:00:01", "10:00+01:00", "not-a-time"]:
            with self.assertRaises(ValueError):
                ref.cutoff_for(dt.date(2026, 1, 1), value)
        with self.assertRaises(ValueError):
            ref.timestamp("2026-01-01T10:00:00")

    def test_real_snapshot_baseline(self):
        report = json.loads((ROOT / "data/derived/quality-report.json").read_text())
        manifest = json.loads((ROOT / "data/manifest.json").read_text())
        wind, actuals = [], []
        for request in manifest["requests"]:
            rows = json.loads((ROOT / request["path"]).read_text())
            (wind if rows[0]["dataset"] == "WINDFOR" else actuals).extend(rows)
        wind, _ = ref.deduplicate(wind, "WINDFOR")
        actuals, _ = ref.deduplicate(actuals, "FUELHH")
        points = ref.comparison(wind, actuals, "09:00")
        computed = ref.metrics(points)
        self.assertEqual(report["unique_rows"]["WINDFOR"], 19272)
        self.assertEqual(report["unique_rows"]["FUELHH_WIND"], 1536)
        self.assertEqual(report["cutoff_local"], "09:00")
        self.assertEqual(computed["matched_hours"], 744)
        self.assertAlmostEqual(computed["mae_mw"], 2038.9126344086021, places=6)
        self.assertAlmostEqual(computed["rmse_mw"], 2504.758652899355, places=6)
        self.assertAlmostEqual(computed["bias_mw"], 1747.8870967741937, places=6)
        self.assertTrue(all(ref.timestamp(p["publish_time"]) <= ref.timestamp(p["cutoff_utc"]) for p in points))


if __name__ == "__main__":
    unittest.main()
