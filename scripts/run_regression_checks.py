from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.section_splitter import split_pdf_pages_by_station_bands
from app.single_section_runner import run_single_cross_section_qc

DEFAULT_CASES_PATH = PROJECT_ROOT / "tests" / "regression_cases.local.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "tests" / "regression_outputs"


def load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"Regression case file not found: {path}\n"
            "Create tests/regression_cases.local.json from tests/regression_cases.example.json."
        )

    with path.open("r", encoding="utf-8") as f:
        cases = json.load(f)

    if not isinstance(cases, list):
        raise ValueError("Regression case file must contain a list of cases.")

    return cases


def count_statuses(checks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"PASS": 0, "REVIEW": 0, "FLAG": 0, "FAIL": 0}

    for check in checks:
        status = str(check.get("status", "")).upper()

        if status in counts:
            counts[status] += 1

    return counts


def summarize_result(result: dict[str, Any], preprocessing: dict[str, Any]) -> dict[str, int]:
    pages = result.get("pages", [])

    slope_checks: list[dict[str, Any]] = []
    elevation_checks: list[dict[str, Any]] = []

    for page in pages:
        slope_checks.extend(page.get("slope_checks", []))
        elevation_checks.extend(page.get("elevation_checks", []))

    slope_counts = count_statuses(slope_checks)
    elevation_counts = count_statuses(elevation_checks)

    return {
        "total_pages": len(pages),
        "source_pages": int(preprocessing.get("source_pages", len(pages))),
        "analysis_pages": int(preprocessing.get("analysis_pages", len(pages))),
        "slope_total": len(slope_checks),
        "slope_pass": slope_counts["PASS"],
        "slope_review": slope_counts["REVIEW"],
        "slope_flag": slope_counts["FLAG"],
        "slope_fail": slope_counts["FAIL"],
        "elevation_total": len(elevation_checks),
        "elevation_pass": elevation_counts["PASS"],
        "elevation_review": elevation_counts["REVIEW"],
        "elevation_flag": elevation_counts["FLAG"],
        "elevation_fail": elevation_counts["FAIL"],
    }


def prepare_pdf_for_regression(pdf_path: Path, output_dir: Path) -> tuple[Path, dict[str, Any]]:
    normalized_pdf = output_dir / f"{pdf_path.stem}_normalized.pdf"

    split_report = split_pdf_pages_by_station_bands(
        input_pdf=pdf_path,
        output_pdf=normalized_pdf,
    )

    source_pages = int(split_report.get("source_pages", 0))
    analysis_pages = int(split_report.get("output_pages", source_pages))

    if analysis_pages > source_pages:
        analysis_pdf = normalized_pdf
    else:
        analysis_pdf = pdf_path

    preprocessing = {
        "source_pages": source_pages,
        "analysis_pages": analysis_pages,
        "was_split": analysis_pages > source_pages,
        "split_report": split_report,
    }

    return analysis_pdf, preprocessing


def compare_summary(case_name: str, actual: dict[str, int], expected: dict[str, int]) -> list[str]:
    failures = []

    for key, expected_value in expected.items():
        actual_value = actual.get(key)

        if actual_value != expected_value:
            failures.append(
                f"{case_name}: expected {key}={expected_value}, got {actual_value}"
            )

    return failures


def run_case(case: dict[str, Any], output_root: Path) -> tuple[bool, dict[str, Any]]:
    name = case.get("name", "unnamed_case")
    pdf_path = PROJECT_ROOT / case["pdf_path"]
    expected = case.get("expected", {})

    if not pdf_path.exists():
        return False, {
            "name": name,
            "error": f"PDF not found: {pdf_path}",
        }

    case_output_dir = output_root / name

    if case_output_dir.exists():
        shutil.rmtree(case_output_dir)

    case_output_dir.mkdir(parents=True, exist_ok=True)

    analysis_pdf, preprocessing = prepare_pdf_for_regression(
        pdf_path=pdf_path,
        output_dir=case_output_dir,
    )

    result = run_single_cross_section_qc(
        pdf_path=analysis_pdf,
        output_root=case_output_dir,
    )

    actual = summarize_result(result=result, preprocessing=preprocessing)
    failures = compare_summary(case_name=name, actual=actual, expected=expected)

    report = {
        "name": name,
        "input_pdf": str(pdf_path),
        "analysis_pdf": str(analysis_pdf),
        "preprocessing": preprocessing,
        "actual": actual,
        "expected": expected,
        "failures": failures,
        "artifacts": result.get("artifacts", {}),
    }

    with (case_output_dir / "regression_result.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return len(failures) == 0, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PDF Engineer Agent regression checks.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help="Path to regression case JSON file.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for regression outputs.",
    )

    args = parser.parse_args()

    cases_path = args.cases.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    cases = load_cases(cases_path)

    print(f"Running {len(cases)} regression case(s)...")
    print(f"Cases: {cases_path}")
    print(f"Output: {output_root}")
    print()

    all_passed = True

    for case in cases:
        name = case.get("name", "unnamed_case")
        print(f"=== {name} ===")

        passed, report = run_case(case, output_root)

        if passed:
            print("PASS")
        else:
            all_passed = False
            print("FAIL")

            if "error" in report:
                print(f"  {report['error']}")

            for failure in report.get("failures", []):
                print(f"  - {failure}")

        print()

    if all_passed:
        print("All regression checks passed.")
        return 0

    print("One or more regression checks failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
