from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import median
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SEARCH_ROOTS = [
    PROJECT_ROOT / "tests" / "regression_outputs",
    PROJECT_ROOT / "web_jobs",
    PROJECT_ROOT / "runs_single_section",
]


def find_latest_results_json() -> Path | None:
    candidates: list[Path] = []

    for root in DEFAULT_SEARCH_ROOTS:
        if root.exists():
            candidates.extend(root.rglob("single_section_results.json"))

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def resolve_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None

    path = Path(path_value)

    if path.is_absolute():
        return path

    return (PROJECT_ROOT / path).resolve()


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None

    values = sorted(values)

    index = int(round((len(values) - 1) * p))
    return values[index]


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"

    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def summarize_candidates(geometry_report: dict) -> dict:
    candidates = geometry_report.get("candidate_slope_lines", [])

    lengths = [
        float(line.get("length_points", 0))
        for line in candidates
        if line.get("length_points") is not None
    ]

    slopes = [
        abs(float(line.get("slope_decimal")))
        for line in candidates
        if line.get("slope_decimal") is not None
    ]

    length_buckets = {
        "lt_4": 0,
        "4_to_8": 0,
        "8_to_16": 0,
        "16_to_32": 0,
        "32_to_64": 0,
        "gte_64": 0,
    }

    slope_buckets = {
        "lt_0_01": 0,
        "0_01_to_0_05": 0,
        "0_05_to_0_15": 0,
        "0_15_to_0_40": 0,
        "0_40_to_0_80": 0,
        "gte_0_80": 0,
    }

    for length in lengths:
        if length < 4:
            length_buckets["lt_4"] += 1
        elif length < 8:
            length_buckets["4_to_8"] += 1
        elif length < 16:
            length_buckets["8_to_16"] += 1
        elif length < 32:
            length_buckets["16_to_32"] += 1
        elif length < 64:
            length_buckets["32_to_64"] += 1
        else:
            length_buckets["gte_64"] += 1

    for slope in slopes:
        if slope < 0.01:
            slope_buckets["lt_0_01"] += 1
        elif slope < 0.05:
            slope_buckets["0_01_to_0_05"] += 1
        elif slope < 0.15:
            slope_buckets["0_05_to_0_15"] += 1
        elif slope < 0.40:
            slope_buckets["0_15_to_0_40"] += 1
        elif slope < 0.80:
            slope_buckets["0_40_to_0_80"] += 1
        else:
            slope_buckets["gte_0_80"] += 1

    return {
        "candidate_count": len(candidates),
        "length_points": {
            "min": min(lengths) if lengths else None,
            "p25": percentile(lengths, 0.25),
            "median": median(lengths) if lengths else None,
            "p75": percentile(lengths, 0.75),
            "max": max(lengths) if lengths else None,
        },
        "abs_slope_decimal": {
            "min": min(slopes) if slopes else None,
            "p25": percentile(slopes, 0.25),
            "median": median(slopes) if slopes else None,
            "p75": percentile(slopes, 0.75),
            "max": max(slopes) if slopes else None,
        },
        "length_buckets": length_buckets,
        "slope_buckets": slope_buckets,
    }


def print_summary(page_number: Any, cleanup: dict, summary: dict) -> None:
    print(f"Page {page_number}")
    print("-" * 80)

    print("Cleanup:")
    for key, value in cleanup.items():
        print(f"  {key}: {value}")

    print()
    print("Candidate length points:")
    for key, value in summary["length_points"].items():
        print(f"  {key}: {fmt(value)}")

    print()
    print("Candidate abs slope:")
    for key, value in summary["abs_slope_decimal"].items():
        print(f"  {key}: {fmt(value)}")

    print()
    print("Length buckets:")
    for key, value in summary["length_buckets"].items():
        print(f"  {key}: {value}")

    print()
    print("Slope buckets:")
    for key, value in summary["slope_buckets"].items():
        print(f"  {key}: {value}")

    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize geometry candidate slope lines from QC results."
    )

    parser.add_argument(
        "--results",
        type=Path,
        help="Path to reports/single_section_results.json. Defaults to latest result.",
    )

    args = parser.parse_args()

    results_path = args.results or find_latest_results_json()

    if results_path is None:
        print("No single_section_results.json files found.")
        return 1

    results_path = results_path.resolve()
    results = load_json(results_path)

    print(f"Results: {results_path}")
    print()

    for page in results.get("pages", []):
        engine_result = page.get("engine_result", {})
        geometry_path = resolve_path(engine_result.get("geometry_report"))

        if geometry_path is None or not geometry_path.exists():
            print(f"Page {page.get('page_number')}: geometry report not found")
            continue

        geometry_report = load_json(geometry_path)
        cleanup = page.get("geometry_cleanup", {})
        summary = summarize_candidates(geometry_report)

        print_summary(
            page_number=page.get("page_number"),
            cleanup=cleanup,
            summary=summary,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
