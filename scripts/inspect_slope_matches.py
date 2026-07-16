from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
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


def load_results(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Results JSON not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def fmt(value: Any, digits: int = 4) -> str:
    if value is None or value == "":
        return "—"

    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def shorten(text: str, width: int = 58) -> str:
    text = str(text or "—")

    if len(text) <= width:
        return text

    return text[: width - 1] + "…"


def collect_slope_rows(
    results: dict[str, Any],
    statuses: set[str] | None,
) -> list[dict[str, Any]]:
    rows = []

    for page in results.get("pages", []):
        page_number = page.get("page_number", "—")

        for index, check in enumerate(page.get("slope_checks", []), start=1):
            status = str(check.get("status", "REVIEW")).upper()

            if statuses is not None and status not in statuses:
                continue

            debug = check.get("match_debug") or {}
            nearest_line = check.get("nearest_measured_line") or {}

            rows.append(
                {
                    "page": page_number,
                    "mark": f"S{index}",
                    "status": status,
                    "printed": check.get("printed_label", "—"),
                    "target": check.get("target_slope"),
                    "measured": check.get("nearest_measured_slope"),
                    "difference": check.get("difference"),
                    "tolerance": check.get("tolerance"),
                    "distance": check.get("distance_to_line_points")
                    or debug.get("distance_to_line_points"),
                    "line_id": nearest_line.get("line_id") or debug.get("chosen_line_id"),
                    "reason": check.get("reason") or debug.get("selection_reason") or "",
                    "selection_reason": debug.get("selection_reason", ""),
                    "decision_reason": debug.get("decision_reason", ""),
                    "candidate_ranking": debug.get("candidate_ranking", []),
                }
            )

    return rows


def print_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No slope matches found for the selected filter.")
        return

    headers = [
        "Page",
        "Mark",
        "Status",
        "Printed",
        "Target",
        "Measured",
        "Diff",
        "Tol",
        "Dist",
        "Line",
        "Reason",
    ]

    widths = [6, 6, 8, 10, 10, 10, 10, 8, 8, 8, 58]

    print(
        " ".join(
            header.ljust(width)
            for header, width in zip(headers, widths, strict=True)
        )
    )

    print("-" * sum(widths))

    for row in rows:
        values = [
            str(row["page"]),
            row["mark"],
            row["status"],
            str(row["printed"]),
            fmt(row["target"]),
            fmt(row["measured"]),
            fmt(row["difference"]),
            fmt(row["tolerance"]),
            fmt(row["distance"], digits=2),
            str(row["line_id"] or "—"),
            shorten(row["reason"]),
        ]

        print(
            " ".join(
                value.ljust(width)
                for value, width in zip(values, widths, strict=True)
            )
        )

    print()
    print("Detailed selection reasons:")
    print("-" * 80)

    for row in rows:
        print(f"{row['page']} {row['mark']} {row['status']}")
        print(f"  Printed: {row['printed']}")
        print(f"  Target: {fmt(row['target'])}")
        print(f"  Measured: {fmt(row['measured'])}")
        print(f"  Difference: {fmt(row['difference'])}")
        print(f"  Tolerance: {fmt(row['tolerance'])}")
        print(f"  Distance to line: {fmt(row['distance'], digits=2)} points")
        print(f"  Chosen line: {row['line_id'] or '—'}")

        if row["selection_reason"]:
            print(f"  Selection reason: {row['selection_reason']}")

        if row["decision_reason"]:
            print(f"  Decision reason: {row['decision_reason']}")

        if row["reason"]:
            print(f"  Reason: {row['reason']}")

        candidates = row.get("candidate_ranking", [])

        if candidates:
            print("  Top candidate lines:")

            for candidate in candidates:
                print(
                    "    "
                    f"#{candidate.get('rank')} "
                    f"line={candidate.get('line_id')} "
                    f"dist={fmt(candidate.get('distance_to_label_points'), digits=2)} "
                    f"measured={fmt(candidate.get('measured_slope'))} "
                    f"diff={fmt(candidate.get('slope_difference'))} "
                    f"within_tol={candidate.get('within_tolerance')}"
                )

        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect slope match decisions from a single_section_results.json file."
    )

    parser.add_argument(
        "--results",
        type=Path,
        help="Path to single_section_results.json. Defaults to latest generated result.",
    )

    parser.add_argument(
        "--status",
        nargs="+",
        default=["FLAG", "REVIEW"],
        help="Statuses to show. Default: FLAG REVIEW.",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Show all slope checks, including PASS.",
    )

    args = parser.parse_args()

    results_path = args.results

    if results_path is None:
        results_path = find_latest_results_json()

    if results_path is None:
        print("No single_section_results.json files found.")
        return 1

    results_path = results_path.resolve()
    results = load_results(results_path)

    if args.all:
        statuses = None
    else:
        statuses = {status.upper() for status in args.status}

    print(f"Results: {results_path}")

    if statuses is None:
        print("Filter: ALL")
    else:
        print(f"Filter: {', '.join(sorted(statuses))}")

    print()

    rows = collect_slope_rows(results, statuses=statuses)
    print_rows(rows)

    return 0


if __name__ == "__main__":
    sys.exit(main())
