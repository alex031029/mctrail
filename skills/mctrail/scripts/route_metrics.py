"""Check normalized road-route metrics; never fetch data or infer a safe route."""

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json
import math
from pathlib import Path
import sys


class InputError(ValueError):
    pass


def object_fields(value, allowed, label):
    if not isinstance(value, dict):
        raise InputError(f"{label} must be an object")
    unknown = value.keys() - allowed
    if unknown:
        raise InputError(f"{label}: unknown fields: {', '.join(sorted(unknown))}")
    return value


def text_field(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{key} must be a non-empty string")
    return value.strip()


def number_field(obj, key, *, zero_allowed=False):
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{key} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0 or (value == 0 and not zero_allowed):
        raise InputError(f"{key} must be finite and {'non-negative' if zero_allowed else 'positive'}")
    return value


def timestamp(value, label):
    if not isinstance(value, str):
        raise InputError(f"{label} must be an ISO datetime with a timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InputError(f"{label} must be an ISO datetime with a timezone") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise InputError(f"{label} must include an explicit timezone")
    return result


def whole_seconds(value):
    if not math.isfinite(value):
        raise InputError("time calculation must be finite")
    return math.ceil(value)


def opening_windows(stop):
    if "opening_windows" not in stop:
        raise InputError("opening_windows is required; use null for unknown hours")
    raw = stop["opening_windows"]
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise InputError("opening_windows must be a list or null")
    text_field(stop, "hours_evidence")
    windows = []
    for entry in raw:
        entry = object_fields(entry, {"opens_at", "closes_at"}, "opening window")
        start = timestamp(entry.get("opens_at"), "opening opens_at")
        end = timestamp(entry.get("closes_at"), "opening closes_at")
        if end <= start:
            raise InputError("opening window must end after it starts")
        windows.append((start, end))
    merged = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def hours_status(windows, arrive, leave):
    if windows is None:
        return "unknown"
    for start, end in windows:
        if start <= arrive < end:
            return "covers_visit" if leave <= end else "closes_during_stop"
    return "closed_at_arrival"


def calculate(data):
    data = object_fields(
        data,
        {
            "data_kind", "mode", "shape", "start_id", "end_id", "departure_at",
            "pace_min_per_km", "target_distance_m", "max_distance_m", "legs", "stops",
        },
        "route",
    )
    if data.get("data_kind") not in ("live", "demo"):
        raise InputError("data_kind must be live or demo")
    mode, shape = data.get("mode"), data.get("shape")
    if mode not in ("run", "cycle"):
        raise InputError("mode must be run or cycle")
    if shape not in ("loop", "point-to-point"):
        raise InputError("shape must be loop or point-to-point")
    start, end = text_field(data, "start_id"), text_field(data, "end_id")
    if shape == "loop" and start != end:
        raise InputError("loop requires identical start_id and end_id")
    if shape == "point-to-point" and start == end:
        raise InputError("point-to-point requires distinct start_id and end_id; use loop")
    departure = timestamp(data.get("departure_at"), "departure_at")
    pace = number_field(data, "pace_min_per_km") if mode == "run" else None
    if mode == "cycle" and "pace_min_per_km" in data:
        raise InputError("pace_min_per_km applies only to run mode")
    target = Decimal(str(number_field(data, "target_distance_m"))) if "target_distance_m" in data else None
    limit = Decimal(str(number_field(data, "max_distance_m"))) if "max_distance_m" in data else None
    legs = data.get("legs")
    if not isinstance(legs, list) or not legs:
        raise InputError("legs must be a non-empty list of road paths")
    expected_source = "amap_walking" if mode == "run" else "amap_cycling"
    distance, durations, previous = Decimal(0), [], start
    for index, leg in enumerate(legs, 1):
        leg = object_fields(
            leg, {"from_id", "to_id", "distance_m", "duration_s", "source", "evidence"},
            f"leg {index}",
        )
        origin, destination = text_field(leg, "from_id"), text_field(leg, "to_id")
        if origin != previous:
            label = "start_id" if index == 1 else "continuous route"
            raise InputError(f"leg {index} does not match {label}")
        if origin == destination:
            raise InputError(f"leg {index} needs distinct endpoints")
        if leg.get("source") != expected_source:
            raise InputError(f"leg {index} source must be {expected_source}")
        text_field(leg, "evidence")
        length = Decimal(str(number_field(leg, "distance_m")))
        if "duration_s" in leg or mode == "cycle":
            duration = number_field(leg, "duration_s")
        if mode == "run":
            duration = length / 1000 * Decimal(str(pace)) * 60
        durations.append(whole_seconds(duration))
        distance += length
        previous = destination
    if previous != end:
        raise InputError("last leg does not match end_id")
    if not math.isfinite(distance):
        raise InputError("total distance_m must be finite")

    raw_stops = data.get("stops", [])
    if not isinstance(raw_stops, list):
        raise InputError("stops must be a list")
    stops = {}
    for stop in raw_stops:
        stop = object_fields(
            stop, {"after_leg", "name", "dwell_minutes", "opening_windows", "hours_evidence"},
            "stop",
        )
        index = stop.get("after_leg")
        if type(index) is not int or not 1 <= index <= len(legs) or index in stops:
            raise InputError("after_leg must be a unique, one-based leg index")
        name = text_field(stop, "name")
        dwell = whole_seconds(Decimal(str(number_field(stop, "dwell_minutes", zero_allowed=True))) * 60)
        stops[index] = (name, dwell, opening_windows(stop))

    within_limit = distance <= limit if limit is not None else None
    warnings = ["synthetic_data_not_navigable"] if data["data_kind"] == "demo" else []
    conflict = within_limit is False
    if conflict:
        warnings.append("distance_limit_exceeded")
    clock, stop_seconds, reports = departure, 0, []
    for index, seconds in enumerate(durations, 1):
        clock += timedelta(seconds=seconds)
        if index not in stops:
            continue
        name, dwell, windows = stops[index]
        leave = clock + timedelta(seconds=dwell)
        status = hours_status(windows, clock, leave)
        if status == "unknown":
            warnings.append(f"stop_{index}_hours_unknown")
        elif status != "covers_visit":
            conflict = True
            warnings.append(f"stop_{index}_{status}")
        reports.append({
            "after_leg": index,
            "name": name,
            "arrive_at": clock.isoformat(),
            "leave_at": leave.isoformat(),
            "hours_status": status,
        })
        stop_seconds += dwell
        clock = leave
    return {
        "data_kind": data["data_kind"],
        "mode": mode,
        "shape": shape,
        "distance_m": float(distance),
        "distance_error_m": float(distance - target) if target is not None else None,
        "within_distance_limit": within_limit,
        "travel_seconds": sum(durations),
        "stop_seconds": stop_seconds,
        "total_seconds": sum(durations) + stop_seconds,
        "finish_at": clock.isoformat(),
        "stops": reports,
        "has_known_conflict": conflict,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Normalized route JSON file, or - for standard input")
    args = parser.parse_args()
    try:
        content = (
            sys.stdin.buffer.read().decode("utf-8-sig")
            if args.input == "-"
            else Path(args.input).read_text(encoding="utf-8-sig")
        )
    except (OSError, UnicodeError):
        print("Cannot read input; supply an existing UTF-8 JSON file.", file=sys.stderr)
        return 2
    try:
        data = json.loads(content.lstrip("\ufeff"))
    except (json.JSONDecodeError, ValueError):
        print("Invalid JSON input.", file=sys.stderr)
        return 2
    try:
        result = calculate(data)
    except InputError as error:
        print(f"Invalid route input: {error}", file=sys.stderr)
        return 2
    except OverflowError:
        print("Invalid route input: time or distance exceeds the supported numeric range.", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
