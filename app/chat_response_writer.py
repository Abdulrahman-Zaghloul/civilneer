from pathlib import Path


def write_chat_response(output_path: str, manifest: dict) -> str:
    summary = manifest.get("summary", {})
    facts = manifest.get("extracted_facts", {})
    artifacts = manifest.get("artifacts", {})

    total_checks = summary.get("total_slope_checks", 0)
    passed = summary.get("slope_checks_passed", 0)
    flagged = summary.get("slope_checks_flagged", 0)
    failed = summary.get("slope_checks_failed", 0)

    stations = facts.get("stations", [])
    decimal_slopes = facts.get("decimal_slopes", [])
    side_slopes = facts.get("side_slopes", [])
    elevations = facts.get("elevations", [])

    lines = []

    lines.append("I reviewed the uploaded engineering PDF using the QC measurement engine.\n")

    if stations:
        lines.append(f"I found station `{', '.join(stations)}`.")
    else:
        lines.append("I could not confidently extract a station value.")

    if decimal_slopes or side_slopes:
        all_slopes = decimal_slopes + side_slopes
        lines.append(f"I found printed slope label(s): `{', '.join(all_slopes)}`.")

    if elevations:
        lines.append(f"I found elevation callouts including: `{', '.join(elevations)}`.")

    lines.append(
        f"\nSlope validation completed: `{total_checks}` check(s), "
        f"`{passed}` passed, `{flagged}` flagged, and `{failed}` failed."
    )

    if failed == 0 and flagged == 0 and total_checks > 0:
        lines.append(
            "\nThe measured PDF geometry matched the printed slope labels within the current tolerance."
        )
    elif flagged > 0 or failed > 0:
        lines.append(
            "\nSome slope checks need review. Open the slope validation report and geometry overlay for details."
        )

    if facts.get("has_not_for_construction_note"):
        lines.append(
            "\nImportant note: the sheet is marked `NOT FOR CONSTRUCTION`, so it should not be treated as construction-ready."
        )

    lines.append("\nGenerated artifacts:")
    lines.append(f"- Senior engineer report: `{artifacts.get('senior_engineer_review')}`")
    lines.append(f"- Geometry overlay: `{artifacts.get('geometry_debug_overlay')}`")
    lines.append(f"- Slope validation report: `{artifacts.get('slope_validation_report')}`")
    lines.append(f"- Full QA report: `{artifacts.get('qa_report')}`")

    lines.append(
        "\nReviewer caution: this automated review should support, not replace, a qualified engineering review."
    )

    output = Path(output_path)
    output.write_text("\n".join(lines), encoding="utf-8")
    return str(output)
