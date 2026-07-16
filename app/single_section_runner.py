from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

from app.agent_runner import run_full_qc
from app.single_section_report_pdf import write_single_section_report_pdf
from app.single_section_marker_pdf import write_single_section_marked_pdf


def safe_name(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9_-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def create_single_section_run_dir(
    pdf_path: str | Path,
    output_root: str | Path = "runs_single_section",
) -> Path:
    pdf_path = Path(pdf_path)
    output_root = Path(output_root)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / f"{safe_name(pdf_path.stem)}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    return run_dir


def extract_page_to_pdf(
    source_pdf: str | Path,
    page_index: int,
    output_pdf: str | Path,
) -> str:
    source_pdf = Path(source_pdf)
    output_pdf = Path(output_pdf)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(source_pdf)
    new_doc = fitz.open()

    new_doc.insert_pdf(doc, from_page=page_index, to_page=page_index)
    new_doc.save(output_pdf)

    new_doc.close()
    doc.close()

    return str(output_pdf)


def count_statuses(checks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "PASS": 0,
        "REVIEW": 0,
        "FLAG": 0,
        "FAIL": 0,
    }

    for check in checks:
        status = check.get("status")

        if status in counts:
            counts[status] += 1
        elif status:
            counts[str(status)] = counts.get(str(status), 0) + 1

    return counts


def page_status_from_checks(
    slope_checks: list[dict[str, Any]],
    elevation_checks: list[dict[str, Any]],
) -> str:
    all_checks = slope_checks + elevation_checks

    if any(check.get("status") in ["FAIL", "FLAG"] for check in all_checks):
        return "FLAG"

    if any(check.get("status") == "REVIEW" for check in all_checks):
        return "REVIEW"

    if not all_checks:
        return "REVIEW"

    return "PASS"


def load_json_file(path: str | Path, default):
    path = Path(path)

    if not path.exists():
        return default

    return json.loads(path.read_text(encoding="utf-8"))


def detect_station_labels_in_pdf(pdf_path: str | Path) -> list[str]:
    doc = fitz.open(pdf_path)
    stations = []

    # PDFs may extract this as:
    # "STA. 170+00.00"
    # or "STA.\n170+00.00"
    # or the station value may appear independently in the sheet title area.
    station_after_sta_pattern = re.compile(
        r"\bSTA\.?\s*(\d+\+\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    any_station_pattern = re.compile(
        r"\b\d{2,5}\+\d{2}(?:\.\d+)?\b"
    )

    for page in doc:
        page_text = page.get_text()
        normalized_text = re.sub(r"\s+", " ", page_text)

        for match in station_after_sta_pattern.finditer(normalized_text):
            stations.append(match.group(1))

        # Fallback: collect station-looking values anywhere on the page.
        # Unique values protect us from duplicate station labels/title block repeats.
        for match in any_station_pattern.finditer(normalized_text):
            stations.append(match.group(0))

    doc.close()

    return sorted(set(stations))


def multiple_cross_section_issue(stations: list[str]) -> dict[str, str] | None:
    if len(stations) <= 1:
        return None

    return {
        "issue": "Multiple cross sections detected on one page",
        "severity": "High",
        "category": "Unsupported Layout",
        "reason": (
            "This page contains multiple station labels "
            f"({', '.join(stations)}). Current single-cross-section mode expects one cross section per page."
        ),
        "suggested_fix": (
            "Split the PDF so each page contains only one cross section, or use a future multi-section layout mode."
        ),
    }


def mark_checks_review_due_to_unsupported_layout(
    checks: list[dict[str, Any]],
    layout_issue: dict[str, str],
) -> list[dict[str, Any]]:
    """
    When multiple cross sections are detected on one page, individual geometry
    matching is not trustworthy. Preserve the measured data for debugging, but
    change the engineering status to REVIEW instead of PASS/FLAG.
    """

    reason = (
        "This check was not fully validated because multiple cross sections were detected "
        "on the same page. Current single-cross-section mode expects one cross section per page."
    )

    updated_checks = []

    for check in checks:
        updated = dict(check)

        updated["raw_status_before_layout_review"] = updated.get("status")
        updated["raw_reason_before_layout_review"] = updated.get("reason")

        updated["status"] = "REVIEW"
        updated["reason"] = reason
        updated["layout_warning"] = layout_issue.get("issue")

        updated_checks.append(updated)

    return updated_checks




def compact_check_for_ai(check: dict[str, Any], check_type: str) -> dict[str, Any]:
    """
    Build a compact evidence packet for AI review.

    The AI should not receive the entire raw app result blindly.
    It should receive the important geometry facts:
    - printed label
    - target value
    - measured value
    - selected point/line
    - candidate ranking
    - current deterministic status
    """

    common = {
        "check_type": check_type,
        "label_id": check.get("label_id"),
        "printed_label": check.get("printed_label") or check.get("label") or check.get("text"),
        "status_before_ai": check.get("status"),
        "method": check.get("method"),
        "reason_before_ai": check.get("reason"),
        "label_center": check.get("label_center"),
        "intersection": check.get("intersection"),
        "target_line": check.get("target_line"),
        "candidate_ranking": check.get("candidate_ranking", []),
    }

    if check_type == "slope":
        match_debug = check.get("match_debug", {}) or {}
        chosen_line = match_debug.get("chosen_line") or check.get("nearest_measured_line") or {}

        common["candidate_ranking"] = (
            check.get("candidate_ranking")
            or match_debug.get("candidate_ranking")
            or []
        )

        common.update(
            {
                "target_slope": check.get("target_slope"),
                "target_slope_percent": check.get("target_slope_percent"),
                "measured_slope": (
                    check.get("measured_slope")
                    or match_debug.get("measured_slope")
                    or check.get("nearest_measured_slope")
                ),
                "measured_slope_percent": (
                    check.get("measured_slope_percent")
                    or check.get("slope_percent")
                    or chosen_line.get("slope_percent")
                ),
                "difference": (
                    check.get("difference")
                    or check.get("slope_difference")
                    or match_debug.get("slope_difference")
                ),
                "tolerance": (
                    check.get("tolerance")
                    or check.get("tolerance_slope")
                    or match_debug.get("tolerance")
                ),
                "selected_candidate": {
                    "line_id": (
                        check.get("line_id")
                        or match_debug.get("chosen_line_id")
                        or chosen_line.get("line_id")
                    ),
                    "run_ft": check.get("run_ft") or chosen_line.get("run_ft"),
                    "rise_ft": check.get("rise_ft") or chosen_line.get("rise_ft"),
                    "distance_to_label_points": (
                        check.get("distance_to_label_points")
                        or check.get("distance_to_line_points")
                        or match_debug.get("distance_to_line_points")
                    ),
                    "pdf_coordinates": (
                        check.get("pdf_coordinates")
                        or match_debug.get("chosen_line_coordinates")
                        or chosen_line.get("pdf_coordinates")
                    ),
                    "slope_percent": chosen_line.get("slope_percent"),
                    "slope_decimal": chosen_line.get("slope_decimal"),
                },
                "match_debug_summary": {
                    "candidate_line_count_total": match_debug.get("candidate_line_count_total"),
                    "candidate_line_count_within_search_radius": match_debug.get("candidate_line_count_within_search_radius"),
                    "match_method": match_debug.get("match_method"),
                    "selection_reason": match_debug.get("selection_reason"),
                    "max_search_distance_points": match_debug.get("max_search_distance_points"),
                },
            }
        )

    if check_type == "elevation":
        common.update(
            {
                "target_elevation": check.get("target_elevation"),
                "measured_elevation": check.get("measured_elevation"),
                "difference_ft": check.get("difference_ft"),
                "abs_difference_ft": check.get("abs_difference_ft"),
                "tolerance_ft": check.get("tolerance_ft"),
                "leader_line": check.get("leader_line"),
                "distance_to_leader_points": check.get("distance_to_leader_points"),
                "anchor_selection_score": check.get("anchor_selection_score"),
                "anchor_elevation_difference": check.get("anchor_elevation_difference"),
                "anchor_expected_y_distance": check.get("anchor_expected_y_distance"),
            }
        )

    return common


def build_ai_evidence(result: dict[str, Any]) -> dict[str, Any]:
    """
    Create a structured evidence file for future AI review.

    This does not call an AI model yet.
    It prepares the data that an AI model will later review.
    """

    evidence_pages = []

    for page in result.get("pages", []):
        slope_checks = [
            compact_check_for_ai(check, "slope")
            for check in page.get("slope_checks", [])
        ]

        elevation_checks = [
            compact_check_for_ai(check, "elevation")
            for check in page.get("elevation_checks", [])
        ]

        evidence_pages.append(
            {
                "page_number": page.get("page_number"),
                "page_status_before_ai": page.get("status"),
                "station_labels": page.get("station_labels", []),
                "layout_issue": page.get("layout_issue"),
                "slope_checks": slope_checks,
                "elevation_checks": elevation_checks,
            }
        )

    return {
        "schema_version": "ai_evidence_v1",
        "purpose": (
            "Evidence packet for AI-assisted review. "
            "The AI should review candidate rankings and recommend PASS, REVIEW, or FLAG. "
            "The AI must not invent measurements."
        ),
        "mode": result.get("mode"),
        "input_pdf": result.get("input_pdf"),
        "run_dir": result.get("run_dir"),
        "summary_before_ai": result.get("summary", {}),
        "pages": evidence_pages,
        "ai_policy": {
            "allowed_statuses": ["PASS", "REVIEW", "FLAG"],
            "low_confidence_status": "REVIEW",
            "do_not_replace_geometry_measurements": True,
            "do_not_claim_engineering_certainty": True,
        },
    }


def run_single_cross_section_qc(
    pdf_path: str | Path,
    output_root: str | Path = "runs_single_section",
) -> dict[str, Any]:
    """
    Simplified QC mode.

    Assumption:
    - The input PDF has one cross section per page.
    - Every page is analyzed independently.
    - No multi-panel detection is used.

    Output:
    - One run folder
    - Temporary one-page PDFs
    - Per-page QC outputs
    - Aggregated JSON results
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    run_dir = create_single_section_run_dir(pdf_path, output_root=output_root)
    pages_dir = run_dir / "single_page_pdfs"
    page_runs_dir = run_dir / "page_runs"
    reports_dir = run_dir / "reports"

    pages_dir.mkdir(parents=True, exist_ok=True)
    page_runs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    page_results = []

    total_slope_checks = []
    total_elevation_checks = []

    print(f"Input PDF: {pdf_path}")
    print(f"Total pages detected: {total_pages}")
    print(f"Single-section run folder: {run_dir}")
    print()

    for page_index in range(total_pages):
        page_number = page_index + 1

        print("=" * 80)
        print(f"Analyzing page {page_number} of {total_pages}...")

        single_page_pdf = pages_dir / f"page_{page_number:03d}.pdf"

        extract_page_to_pdf(
            source_pdf=pdf_path,
            page_index=page_index,
            output_pdf=single_page_pdf,
        )

        page_output_root = page_runs_dir / f"page_{page_number:03d}"

        try:
            engine_result = run_full_qc(
                str(single_page_pdf),
                output_base_dir=str(page_output_root),
            )

            slope_checks = load_json_file(
                engine_result.get("slope_validation_report", ""),
                default=[],
            )

            elevation_checks = load_json_file(
                engine_result.get("elevation_validation_report", ""),
                default=[],
            )

            qa_report = load_json_file(
                engine_result.get("qa_report", ""),
                default={},
            )

            geometry_report = load_json_file(
                engine_result.get("geometry_report", ""),
                default={},
            )

            geometry_cleanup = geometry_report.get("geometry_cleanup", {})

            station_labels = detect_station_labels_in_pdf(single_page_pdf)
            layout_issue = multiple_cross_section_issue(station_labels)

            basic_issues = qa_report.get("basic_issues", [])

            if layout_issue:
                basic_issues = [layout_issue] + basic_issues

                slope_checks = mark_checks_review_due_to_unsupported_layout(
                    slope_checks,
                    layout_issue,
                )

                elevation_checks = mark_checks_review_due_to_unsupported_layout(
                    elevation_checks,
                    layout_issue,
                )

                status = "REVIEW"
            else:
                status = page_status_from_checks(slope_checks, elevation_checks)

            page_result = {
                "page_number": page_number,
                "status": status,
                "input_page_pdf": str(single_page_pdf),
                "engine_result": engine_result,
                "summary": {
                    "slope_checks": {
                        "total": len(slope_checks),
                        **count_statuses(slope_checks),
                    },
                    "elevation_checks": {
                        "total": len(elevation_checks),
                        **count_statuses(elevation_checks),
                    },
                    "basic_issue_count": len(basic_issues),
                },
                "geometry_cleanup": geometry_cleanup,
                "slope_checks": slope_checks,
                "elevation_checks": elevation_checks,
                "basic_issues": basic_issues,
            }

            total_slope_checks.extend(slope_checks)
            total_elevation_checks.extend(elevation_checks)

        except Exception as error:
            page_result = {
                "page_number": page_number,
                "status": "FAIL",
                "input_page_pdf": str(single_page_pdf),
                "error": str(error),
                "summary": {
                    "slope_checks": {
                        "total": 0,
                        "PASS": 0,
                        "REVIEW": 0,
                        "FLAG": 0,
                        "FAIL": 0,
                    },
                    "elevation_checks": {
                        "total": 0,
                        "PASS": 0,
                        "REVIEW": 0,
                        "FLAG": 0,
                        "FAIL": 0,
                    },
                    "basic_issue_count": 0,
                },
                "geometry_cleanup": {},
                "slope_checks": [],
                "elevation_checks": [],
                "basic_issues": [],
            }

        print(
            f"Page {page_number} status: {page_result['status']} | "
            f"slopes: {page_result['summary']['slope_checks']['total']} | "
            f"elevations: {page_result['summary']['elevation_checks']['total']}"
        )

        page_results.append(page_result)

    page_status_counts = count_statuses(
        [{"status": page["status"]} for page in page_results]
    )

    result = {
        "mode": "single_cross_section",
        "input_pdf": str(pdf_path),
        "run_dir": str(run_dir),
        "total_pages": total_pages,
        "summary": {
            "page_statuses": page_status_counts,
            "slope_checks": {
                "total": len(total_slope_checks),
                **count_statuses(total_slope_checks),
            },
            "elevation_checks": {
                "total": len(total_elevation_checks),
                **count_statuses(total_elevation_checks),
            },
        },
        "pages": page_results,
        "artifacts": {
            "results_json": str(reports_dir / "single_section_results.json"),
            "ai_evidence_json": str(reports_dir / "ai_evidence.json"),
            "report_pdf": str(reports_dir / "single_section_report.pdf"),
            "marked_pdf": str(reports_dir / "single_section_marked.pdf"),
        },
    }

    report_pdf_path = reports_dir / "single_section_report.pdf"
    marked_pdf_path = reports_dir / "single_section_marked.pdf"

    write_single_section_report_pdf(result, report_pdf_path)
    write_single_section_marked_pdf(result, pdf_path, marked_pdf_path)

    results_path = reports_dir / "single_section_results.json"
    results_path.write_text(json.dumps(result, indent=4), encoding="utf-8")

    ai_evidence_path = reports_dir / "ai_evidence.json"
    ai_evidence = build_ai_evidence(result)
    ai_evidence_path.write_text(json.dumps(ai_evidence, indent=4), encoding="utf-8")

    print()
    print("=" * 80)
    print("Single-section QC complete.")
    print(f"Results JSON: {results_path}")
    print(f"AI evidence JSON: {ai_evidence_path}")

    return result


if __name__ == "__main__":
    result = run_single_cross_section_qc(
        pdf_path="input_pdfs/1st_xs.pdf",
        output_root="runs_single_section",
    )

    print()
    print(json.dumps(result["summary"], indent=4))
