from pathlib import Path
from datetime import datetime
import json


def write_run_manifest(
    output_path: str,
    run_dir: str,
    pdf_path: str,
    qa_report: dict,
    artifacts: dict,
) -> str:
    manifest = {
        "status": "completed",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_pdf": pdf_path,
        "run_dir": run_dir,
        "summary": {
            "total_slope_checks": qa_report.get("slope_validation_summary", {}).get("total_checks", 0),
            "slope_checks_passed": qa_report.get("slope_validation_summary", {}).get("passed", 0),
            "slope_checks_flagged": qa_report.get("slope_validation_summary", {}).get("flagged", 0),
            "slope_checks_failed": qa_report.get("slope_validation_summary", {}).get("failed", 0),

            "total_elevation_checks": qa_report.get("elevation_validation_summary", {}).get("total_checks", 0),
            "elevation_checks_passed": qa_report.get("elevation_validation_summary", {}).get("passed", 0),
            "elevation_checks_flagged": qa_report.get("elevation_validation_summary", {}).get("flagged", 0),
            "elevation_checks_failed": qa_report.get("elevation_validation_summary", {}).get("failed", 0),

            "total_basic_issues": qa_report.get("total_basic_issues", 0),
            "total_vector_lines": qa_report.get("geometry_summary", {}).get("total_vector_lines", 0),
            "candidate_slope_lines": qa_report.get("geometry_summary", {}).get("total_candidate_slope_lines", 0),
        },
        "extracted_facts": qa_report.get("extracted_facts", {}),
        "artifacts": artifacts,
    }

    output = Path(output_path)
    output.write_text(json.dumps(manifest, indent=4), encoding="utf-8")

    return str(output)
