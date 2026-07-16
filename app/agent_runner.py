from pathlib import Path
from datetime import datetime
import json
import re

from app.pdf_reader import extract_text_from_pdf, render_pdf_pages
from app.fact_extractor import extract_sheet_facts
from app.geometry_extractor import build_geometry_report
from app.geometry_debug import create_geometry_debug_overlay
from app.slope_label_debug import create_slope_label_match_overlay
from app.slope_label_extractor import extract_slope_label_occurrences

from app.elevation_label_extractor import (
    build_elevation_grid_calibration,
    extract_elevation_label_occurrences,
)
from app.elevation_debug import create_elevation_label_overlay

from app.checks.basic_sheet_checks import run_basic_sheet_checks
from app.checks.spatial_slope_checks import validate_slope_label_occurrences
from app.checks.elevation_checks import validate_elevation_label_occurrences

from app.report_writer import write_senior_review_report
from app.manifest_writer import write_run_manifest
from app.chat_response_writer import write_chat_response


def safe_name(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9_-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def create_run_folder(pdf_path: str, output_base_dir: str = "runs") -> Path:
    pdf_stem = safe_name(Path(pdf_path).stem)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(output_base_dir) / f"{pdf_stem}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def run_full_qc(pdf_path: str, output_base_dir: str = "runs") -> dict:
    run_dir = create_run_folder(pdf_path, output_base_dir)

    output_reports_dir = run_dir / "reports"
    rendered_pages_dir = run_dir / "rendered_pages"

    output_reports_dir.mkdir(parents=True, exist_ok=True)
    rendered_pages_dir.mkdir(parents=True, exist_ok=True)

    extracted_text_path = output_reports_dir / "extracted_text.txt"
    qa_report_path = output_reports_dir / "qa_report.json"
    geometry_report_path = output_reports_dir / "geometry_report.json"
    slope_validation_path = output_reports_dir / "slope_validation_report.json"
    elevation_validation_path = output_reports_dir / "elevation_validation_report.json"

    debug_overlay_path = output_reports_dir / "geometry_debug_overlay.png"
    slope_match_overlay_path = output_reports_dir / "slope_label_match_overlay.png"
    elevation_overlay_path = output_reports_dir / "elevation_label_overlay.png"

    senior_report_path = output_reports_dir / "senior_engineer_review.md"
    manifest_path = run_dir / "manifest.json"
    chat_response_path = run_dir / "chat_response.md"

    print("Reading PDF...")
    text = extract_text_from_pdf(pdf_path)

    print("Saving extracted text...")
    extracted_text_path.write_text(text, encoding="utf-8")

    print("Rendering PDF pages...")
    rendered_pages = render_pdf_pages(pdf_path, str(rendered_pages_dir))

    print("Extracting sheet facts...")
    facts = extract_sheet_facts(text)

    print("Extracting and measuring PDF geometry...")
    geometry_report = build_geometry_report(pdf_path, text)

    print("Extracting printed slope label occurrences...")
    slope_label_occurrences = extract_slope_label_occurrences(pdf_path)

    print("Validating each printed slope label occurrence against measured geometry...")
    slope_validation = validate_slope_label_occurrences(
        slope_label_occurrences,
        geometry_report,
    )

    print("Calibrating elevation grid...")
    elevation_grid_calibration = build_elevation_grid_calibration(pdf_path)

    print("Extracting elevation label occurrences...")
    elevation_label_occurrences = extract_elevation_label_occurrences(pdf_path)

    print("Validating elevation labels against grid position...")
    elevation_validation = validate_elevation_label_occurrences(
        elevation_label_occurrences,
        elevation_grid_calibration,
        pdf_path=pdf_path,
    )

    print("Creating geometry debug overlay...")
    debug_overlay = create_geometry_debug_overlay(
        rendered_pages[0],
        geometry_report.get("candidate_slope_lines", []),
        str(debug_overlay_path),
    )

    print("Creating slope label match overlay...")
    slope_match_overlay = create_slope_label_match_overlay(
        rendered_pages[0],
        slope_validation,
        geometry_report,
        str(slope_match_overlay_path),
    )

    print("Creating elevation label overlay...")
    elevation_overlay = create_elevation_label_overlay(
        rendered_pages[0],
        elevation_validation,
        str(elevation_overlay_path),
    )

    print("Running basic engineering checks...")
    basic_issues = run_basic_sheet_checks(text, facts)

    qa_report = {
        "input_pdf": pdf_path,
        "run_dir": str(run_dir),
        "rendered_pages": rendered_pages,
        "extracted_facts": facts,
        "slope_label_occurrences": slope_label_occurrences,
        "elevation_grid_calibration": elevation_grid_calibration,
        "elevation_label_occurrences": elevation_label_occurrences,
        "geometry_summary": {
            "scales": geometry_report.get("scales"),
            "total_vector_lines": geometry_report.get("total_vector_lines"),
            "total_candidate_slope_lines": geometry_report.get("total_candidate_slope_lines"),
            "debug_overlay": debug_overlay,
            "slope_label_match_overlay": slope_match_overlay,
            "elevation_label_overlay": elevation_overlay,
        },
        "slope_validation_summary": {
            "total_checks": len(slope_validation),
            "passed": sum(1 for check in slope_validation if check["status"] == "PASS"),
            "flagged": sum(1 for check in slope_validation if check["status"] == "FLAG"),
            "failed": sum(1 for check in slope_validation if check["status"] == "FAIL"),
        },
        "elevation_validation_summary": {
            "total_checks": len(elevation_validation),
            "passed": sum(1 for check in elevation_validation if check["status"] == "PASS"),
            "flagged": sum(1 for check in elevation_validation if check["status"] == "FLAG"),
            "failed": sum(1 for check in elevation_validation if check["status"] == "FAIL"),
        },
        "total_basic_issues": len(basic_issues),
        "basic_issues": [issue.model_dump() for issue in basic_issues],
    }

    print("Writing reports...")
    qa_report_path.write_text(json.dumps(qa_report, indent=4), encoding="utf-8")
    geometry_report_path.write_text(json.dumps(geometry_report, indent=4), encoding="utf-8")
    slope_validation_path.write_text(json.dumps(slope_validation, indent=4), encoding="utf-8")
    elevation_validation_path.write_text(json.dumps(elevation_validation, indent=4), encoding="utf-8")

    senior_report = write_senior_review_report(
        output_path=str(senior_report_path),
        pdf_path=pdf_path,
        facts=facts,
        geometry_report=geometry_report,
        slope_validation=slope_validation,
        basic_issues=basic_issues,
    )

    artifacts = {
        "qa_report": str(qa_report_path),
        "geometry_report": str(geometry_report_path),
        "slope_validation_report": str(slope_validation_path),
        "elevation_validation_report": str(elevation_validation_path),
        "geometry_debug_overlay": str(debug_overlay_path),
        "slope_label_match_overlay": slope_match_overlay,
        "elevation_label_overlay": elevation_overlay,
        "senior_engineer_review": senior_report,
        "rendered_pages": rendered_pages,
    }

    manifest = write_run_manifest(
        output_path=str(manifest_path),
        run_dir=str(run_dir),
        pdf_path=pdf_path,
        qa_report=qa_report,
        artifacts=artifacts,
    )

    manifest_data = json.loads(Path(manifest).read_text(encoding="utf-8"))

    chat_response = write_chat_response(
        output_path=str(chat_response_path),
        manifest=manifest_data,
    )

    return {
        "run_dir": str(run_dir),
        "qa_report": str(qa_report_path),
        "geometry_report": str(geometry_report_path),
        "slope_validation_report": str(slope_validation_path),
        "elevation_validation_report": str(elevation_validation_path),
        "geometry_debug_overlay": str(debug_overlay_path),
        "slope_label_match_overlay": slope_match_overlay,
        "elevation_label_overlay": elevation_overlay,
        "senior_engineer_review": senior_report,
        "manifest": manifest,
        "chat_response": chat_response,
    }
