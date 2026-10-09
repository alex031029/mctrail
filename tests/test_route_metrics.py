import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "mctrail" / "scripts" / "route_metrics.py"


def night_loop():
    return {
        "data_kind": "demo",
        "mode": "run",
        "shape": "loop",
        "start_id": "A",
        "end_id": "A",
        "departure_at": "2026-10-09T23:50:00+08:00",
        "pace_min_per_km": 6,
        "target_distance_m": 8000,
        "max_distance_m": 8500,
        "legs": [
            {
                "from_id": "A",
                "to_id": "B",
                "distance_m": 4000,
                "source": "amap_walking",
                "evidence": "synthetic-road-A-B",
            },
            {
                "from_id": "B",
                "to_id": "A",
                "distance_m": 4200,
                "source": "amap_walking",
                "evidence": "synthetic-road-B-A",
            },
        ],
        "stops": [
            {
                "after_leg": 1,
                "name": "Fictional stop B",
                "dwell_minutes": 15,
                "hours_evidence": "synthetic-dated-hours",
                "opening_windows": [
                    {
                        "opens_at": "2026-10-09T18:00:00+08:00",
                        "closes_at": "2026-10-10T00:20:00+08:00",
                    }
                ],
            }
        ],
    }


def cycling_route():
    return {
        "data_kind": "demo",
        "mode": "cycle",
        "shape": "point-to-point",
        "start_id": "A",
        "end_id": "C",
        "departure_at": "2026-10-09T17:00:00+08:00",
        "max_distance_m": 6500,
        "legs": [
            {
                "from_id": "A",
                "to_id": "B",
                "distance_m": 3400,
                "duration_s": 600,
                "source": "amap_cycling",
                "evidence": "synthetic-road-A-B",
            },
            {
                "from_id": "B",
                "to_id": "C",
                "distance_m": 2600,
                "duration_s": 480,
                "source": "amap_cycling",
                "evidence": "synthetic-road-B-C",
            },
        ],
        "stops": [
            {
                "after_leg": 1,
                "name": "Fictional stop B",
                "dwell_minutes": 10,
                "opening_windows": None,
            }
        ],
    }


class RouteMetricsTests(unittest.TestCase):
    def invoke(self, data):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "-"],
            input=json.dumps(data),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=tempfile.gettempdir(),
            check=False,
        )

    def result(self, data):
        process = self.invoke(data)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        return json.loads(process.stdout)

    def invalid(self, data, message):
        process = self.invoke(data)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")
        self.assertIn(message, process.stderr)
        self.assertNotIn("Traceback", process.stderr)

    def test_running_loop_checks_entire_stop_across_midnight(self):
        result = self.result(night_loop())
        self.assertEqual(result["distance_m"], 8200)
        self.assertEqual(result["distance_error_m"], 200)
        self.assertTrue(result["within_distance_limit"])
        self.assertEqual(result["travel_seconds"], 2952)
        self.assertEqual(result["total_seconds"], 3852)
        self.assertEqual(result["finish_at"], "2026-10-10T00:54:12+08:00")
        stop = result["stops"][0]
        self.assertEqual(stop["arrive_at"], "2026-10-10T00:14:00+08:00")
        self.assertEqual(stop["leave_at"], "2026-10-10T00:29:00+08:00")
        self.assertEqual(stop["hours_status"], "closes_during_stop")
        self.assertTrue(result["has_known_conflict"])
        self.assertEqual(result["data_kind"], "demo")

    def test_cycling_uses_road_duration_and_preserves_unknown_hours(self):
        result = self.result(cycling_route())
        self.assertEqual(result["distance_m"], 6000)
        self.assertEqual(result["travel_seconds"], 1080)
        self.assertEqual(result["stop_seconds"], 600)
        self.assertEqual(result["finish_at"], "2026-10-09T17:28:00+08:00")
        self.assertEqual(result["stops"][0]["arrive_at"], "2026-10-09T17:10:00+08:00")
        self.assertEqual(result["stops"][0]["hours_status"], "unknown")
        self.assertIn("stop_1_hours_unknown", result["warnings"])
        self.assertFalse(result["has_known_conflict"])

    def test_leaving_exactly_at_closing_is_covered(self):
        data = night_loop()
        data["stops"][0]["dwell_minutes"] = 6
        result = self.result(data)
        self.assertEqual(result["stops"][0]["hours_status"], "covers_visit")

    def test_arriving_exactly_at_closing_is_closed(self):
        data = night_loop()
        data["stops"][0]["opening_windows"][0]["closes_at"] = "2026-10-10T00:14:00+08:00"
        self.assertEqual(self.result(data)["stops"][0]["hours_status"], "closed_at_arrival")

    def test_adjacent_opening_windows_cover_one_continuous_visit(self):
        data = night_loop()
        data["stops"][0]["opening_windows"].append(
            {
                "opens_at": "2026-10-10T00:20:00+08:00",
                "closes_at": "2026-10-10T01:00:00+08:00",
            }
        )
        self.assertEqual(self.result(data)["stops"][0]["hours_status"], "covers_visit")

    def test_empty_confirmed_opening_windows_mean_closed(self):
        data = night_loop()
        data["stops"][0]["opening_windows"] = []
        result = self.result(data)
        self.assertEqual(result["stops"][0]["hours_status"], "closed_at_arrival")

    def test_multiple_stops_change_later_arrival_times(self):
        data = cycling_route()
        data["stops"].append(
            {
                "after_leg": 2,
                "name": "Fictional stop C",
                "dwell_minutes": 5,
                "opening_windows": None,
            }
        )
        result = self.result(data)
        self.assertEqual(result["stops"][1]["arrive_at"], "2026-10-09T17:28:00+08:00")
        self.assertEqual(result["finish_at"], "2026-10-09T17:33:00+08:00")

    def test_distance_limit_conflict_is_reported_not_silently_relaxed(self):
        data = night_loop()
        data["legs"][1]["distance_m"] = 4600
        result = self.result(data)
        self.assertFalse(result["within_distance_limit"])
        self.assertEqual(result["distance_m"], 8600)
        self.assertTrue(result["has_known_conflict"])
        self.assertIn("distance_limit_exceeded", result["warnings"])

    def test_decimal_distances_do_not_exceed_an_exact_limit(self):
        data = cycling_route()
        data["legs"][0]["distance_m"] = 1000.1
        data["legs"][1]["distance_m"] = 1000.2
        data["max_distance_m"] = 2000.3
        result = self.result(data)
        self.assertTrue(result["within_distance_limit"])
        self.assertEqual(result["distance_m"], 2000.3)

    def test_route_shape_and_leg_continuity_are_checked(self):
        cases = []
        data = night_loop()
        data["legs"][1]["from_id"] = "X"
        cases.append((data, "continuous"))
        data = night_loop()
        data["end_id"] = "C"
        cases.append((data, "loop"))
        data = cycling_route()
        data["legs"][-1]["to_id"] = "D"
        cases.append((data, "end_id"))
        data = cycling_route()
        data["start_id"] = "X"
        cases.append((data, "start_id"))
        for data, message in cases:
            with self.subTest(message=message):
                self.invalid(data, message)

    def test_missing_or_wrong_road_evidence_is_rejected(self):
        for field, value, message in [
            ("source", "straight_line", "source"),
            ("source", "amap_cycling", "source"),
            ("evidence", "", "evidence"),
        ]:
            data = night_loop()
            data["legs"][0][field] = value
            with self.subTest(field=field, value=value):
                self.invalid(data, message)

    def test_invalid_numeric_inputs_do_not_produce_routes(self):
        for value in [-1, 0, True, "4000", float("nan"), float("inf")]:
            data = night_loop()
            data["legs"][0]["distance_m"] = value
            with self.subTest(value=value):
                self.invalid(data, "distance_m")
        data = cycling_route()
        del data["legs"][0]["duration_s"]
        self.invalid(data, "duration_s")
        data = night_loop()
        del data["pace_min_per_km"]
        self.invalid(data, "pace_min_per_km")
        data = night_loop()
        data["pace_min_per_km"] = 1e308
        self.invalid(data, "time")

    def test_explicit_timezones_and_valid_windows_are_required(self):
        data = night_loop()
        data["departure_at"] = "2026-10-09T23:50:00"
        self.invalid(data, "timezone")
        data = night_loop()
        data["stops"][0]["opening_windows"][0]["closes_at"] = "2026-10-09T17:00:00+08:00"
        self.invalid(data, "opening")
        data = night_loop()
        del data["stops"][0]["hours_evidence"]
        self.invalid(data, "hours_evidence")

    def test_duplicate_stop_empty_legs_and_unknown_fields_are_rejected(self):
        data = night_loop()
        data["stops"].append(copy.deepcopy(data["stops"][0]))
        self.invalid(data, "after_leg")
        data = night_loop()
        data["legs"] = []
        self.invalid(data, "legs")
        data = night_loop()
        data["max_distnace_m"] = 8500
        self.invalid(data, "max_distnace_m")

    def test_missing_bound_remains_unknown_not_implicitly_satisfied(self):
        data = cycling_route()
        del data["max_distance_m"]
        result = self.result(data)
        self.assertIsNone(result["within_distance_limit"])
        self.assertIsNone(result["distance_error_m"])

    def test_invalid_json_and_missing_file_have_clear_cli_errors(self):
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "-"],
            input="{",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("Invalid JSON", process.stderr)
        process = subprocess.run(
            [sys.executable, str(SCRIPT), str(ROOT / "does-not-exist.json")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("Cannot read input", process.stderr)

    def test_utf8_stdin_preserves_chinese_names_with_legacy_host_encoding(self):
        data = cycling_route()
        data["stops"][0]["name"] = "\u9ea6\u5f53\u52b3"
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        for prefix in (b"", b"\xef\xbb\xbf"):
            with self.subTest(bom=bool(prefix)):
                process = subprocess.run(
                    [sys.executable, str(SCRIPT), "-"],
                    input=prefix + payload,
                    capture_output=True,
                    env={**os.environ, "PYTHONIOENCODING": "cp1252"},
                    check=False,
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                result = json.loads(process.stdout.decode("utf-8"))
                self.assertEqual(result["stops"][0]["name"], data["stops"][0]["name"])


if __name__ == "__main__":
    unittest.main()
