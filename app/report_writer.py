from pathlib import Path


def fmt(value, decimals=2):
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def format_slope_check(check: dict) -> str:
    printed = check.get("printed_label", "N/A")
    target = check.get("target_slope")
    measured = check.get("nearest_measured_slope")
    difference = check.get("difference")
    status = check.get("status", "UNKNOWN")
    reason = check.get("reason", "")

    line = check.get("nearest_measured_line") or {}
    line_id = line.get("line_id")
    run_ft = line.get("run_ft")
    rise_ft = line.get("rise_ft")
    slope_percent = line.get("slope_percent")

    lines = [
        f"- **{status}** — Printed slope `{printed}` was checked against measured geometry.",
        f"  - Target slope: `{fmt(target, 4)}`",
        f"  - Measured slope: `{fmt(measured, 4)}`",
        f"  - Difference: `{fmt(difference, 4)}`",
        f"  - Measured line ID: `{line_id if line_id is not None else 'N/A'}`",
        f"  - Run: `{fmt(run_ft, 2)} ft`",
        f"  - Rise: `{fmt(rise_ft, 2)} ft`",
        f"  - Slope percent: `{fmt(slope_percent, 2)}%`",
    ]

    if reason:
        lines.append(f"  - Reason: {reason}")

    return "\n".join(lines)


def format_basic_issue(issue) -> str:
    severity = getattr(issue, "severity", "Info")
    category = getattr(issue, "category", "General")
    message = getattr(issue, "message", "")
    suggested_fix = getattr(issue, "suggested_fix", "")

    lines = [
        f"- **{severity}** — {message}",
        f"  - Category: {category}",
    ]

    if suggested_fix:
        lines.append(f"  - Suggested fix: {suggested_fix}")

    return "\n".join(lines)


def write_senior_review_report(
    output_path: str,
    pdf_path: str,
    facts: dict,
    geometry_report: dict,
    slope_validation: list[dict],
    basic_issues: list,
) -> str:
    total_slope_checks = len(slope_validation)
    passed = sum(1 for check in slope_validation if check.get("status") == "PASS")
    flagged = sum(1 for check in slope_validation if check.get("status") == "FLAG")
    failed = sum(1 for check in slope_validation if check.get("status") == "FAIL")

    lines = []

    lines.append("# Engineering QC Review Report")
    lines.append("")
    lines.append(f"**Input PDF:** `{pdf_path}`")
    lines.append("")

    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append(
        f"The slope validation tool reviewed `{total_slope_checks}` printed slope label check(s). "
        f"`{passed}` passed, `{flagged}` were flagged, and `{failed}` failed."
    )
    lines.append("")

    if facts.get("has_not_for_construction_note"):
        lines.append(
            "**Important:** This sheet is marked `NOT FOR CONSTRUCTION`. "
            "It should not be treated as a construction-ready document unless a proper issued-for-construction version is provided."
        )
        lines.append("")

    lines.append("## 2. Extracted Sheet Information")
    lines.append("")
    lines.append(f"- Stations found: `{facts.get('stations', [])}`")
    lines.append(f"- Elevations found: `{facts.get('elevations', [])}`")
    lines.append(f"- Top of bank elevations: `{facts.get('top_of_bank_elevations', [])}`")
    lines.append(f"- Bottom elevations: `{facts.get('bottom_elevations', [])}`")
    lines.append(f"- Decimal slope labels: `{facts.get('decimal_slopes', [])}`")
    lines.append(f"- Side slope labels: `{facts.get('side_slopes', [])}`")
    lines.append(f"- Financial project IDs: `{facts.get('financial_project_ids', [])}`")
    lines.append("")

    lines.append("## 3. Geometry Measurement Summary")
    lines.append("")
    scales = geometry_report.get("scales", {})
    lines.append(f"- Vertical scale: `{scales.get('vertical_ft_per_inch', 'N/A')} ft/in`")
    lines.append(f"- Horizontal scale: `{scales.get('horizontal_ft_per_inch', 'N/A')} ft/in`")
    lines.append(f"- Total vector lines found: `{geometry_report.get('total_vector_lines', 0)}`")
    lines.append(f"- Candidate engineering slope lines: `{geometry_report.get('total_candidate_slope_lines', 0)}`")
    lines.append("")

    lines.append("## 4. Slope Validation Results")
    lines.append("")

    if slope_validation:
        for check in slope_validation:
            lines.append(format_slope_check(check))
            lines.append("")
    else:
        lines.append("No slope validation checks were generated.")
        lines.append("")

    lines.append("## 5. Basic QA/QC Issues")
    lines.append("")

    if basic_issues:
        for issue in basic_issues:
            lines.append(format_basic_issue(issue))
            lines.append("")
    else:
        lines.append("No basic QA/QC issues were detected.")
        lines.append("")

    lines.append("## 6. Reviewer Notes")
    lines.append("")
    lines.append(
        "This report is generated from automated PDF text extraction and vector geometry measurement. "
        "The results should be reviewed by a qualified engineer, especially where linework contains overlapping CAD fragments, "
        "duplicated vector segments, unclear labels, multiple section panels, or unmatched labels."
    )
    lines.append("")

    output = Path(output_path)
    output.write_text("\n".join(lines), encoding="utf-8")

    return str(output)
