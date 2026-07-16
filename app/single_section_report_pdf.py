from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _safe(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _status_color(status: str):
    if status == "PASS":
        return colors.HexColor("#188038")
    if status == "REVIEW":
        return colors.HexColor("#f29900")
    if status in ["FLAG", "FAIL"]:
        return colors.HexColor("#d93025")
    return colors.black


def _computed_total(summary: dict[str, Any]) -> int:
    if summary.get("total") is not None:
        return int(summary.get("total", 0))

    return int(summary.get("PASS", 0)) + int(summary.get("REVIEW", 0)) + int(summary.get("FLAG", 0)) + int(summary.get("FAIL", 0))


def _status_table(summary: dict[str, Any], title: str):
    total = _computed_total(summary)

    data = [
        [title, "Total", "PASS", "REVIEW", "FLAG", "FAIL"],
        [
            "",
            _safe(total),
            _safe(summary.get("PASS", 0)),
            _safe(summary.get("REVIEW", 0)),
            _safe(summary.get("FLAG", 0)),
            _safe(summary.get("FAIL", 0)),
        ],
    ]

    table = Table(
        data,
        colWidths=[
            1.5 * inch,
            0.8 * inch,
            0.8 * inch,
            0.9 * inch,
            0.8 * inch,
            0.8 * inch,
        ],
    )

    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TEXTCOLOR", (2, 1), (2, 1), _status_color("PASS")),
                ("TEXTCOLOR", (3, 1), (3, 1), _status_color("REVIEW")),
                ("TEXTCOLOR", (4, 1), (4, 1), _status_color("FLAG")),
                ("TEXTCOLOR", (5, 1), (5, 1), _status_color("FAIL")),
            ]
        )
    )

    return table


def _slope_measured_value(check: dict[str, Any]):
    measured = (
        check.get("measured_slope")
        or check.get("nearest_measured_slope")
        or check.get("slope_decimal")
        or check.get("measured_value")
    )

    if isinstance(measured, (int, float)):
        return abs(float(measured))

    return measured


def _slope_tolerance_value(check: dict[str, Any]):
    if check.get("tolerance") is not None:
        return check.get("tolerance")

    label = str(check.get("printed_label", ""))

    if ":" in label:
        return 0.04

    return 0.0065


def _slope_reason(check: dict[str, Any]) -> str:
    status = check.get("status")

    if status == "PASS":
        return ""

    if check.get("reason"):
        return str(check.get("reason"))

    if status == "REVIEW":
        return "Automated check could not confidently validate this slope; manual review required."

    if status in ["FLAG", "FAIL"]:
        return "Automated check found a potential slope mismatch or processing issue."

    return ""


def _make_slope_table(checks: list[dict[str, Any]], styles):
    if not checks:
        return Paragraph("No slope checks found on this page.", styles["BodyText"])

    data = [["#", "Label", "Target", "Measured", "Diff", "Tol.", "Status", "Reason"]]

    for idx, check in enumerate(checks, start=1):
        data.append(
            [
                str(idx),
                _safe(check.get("printed_label")),
                _safe(check.get("target_slope")),
                _safe(_slope_measured_value(check)),
                _safe(check.get("difference")),
                _safe(_slope_tolerance_value(check)),
                _safe(check.get("status")),
                Paragraph(_safe(_slope_reason(check), ""), styles["SmallBody"]),
            ]
        )

    table = Table(
        data,
        repeatRows=1,
        colWidths=[
            0.35 * inch,
            0.75 * inch,
            0.75 * inch,
            0.85 * inch,
            0.65 * inch,
            0.55 * inch,
            0.7 * inch,
            2.3 * inch,
        ],
    )

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]

    for row_index, check in enumerate(checks, start=1):
        style.append(("TEXTCOLOR", (6, row_index), (6, row_index), _status_color(check.get("status", ""))))

    table.setStyle(TableStyle(style))
    return table


def _make_elevation_table(checks: list[dict[str, Any]], styles):
    if not checks:
        return Paragraph("No elevation checks found on this page.", styles["BodyText"])

    data = [["#", "Label", "Target EL", "Measured EL", "Diff ft", "Tol.", "Status", "Reason"]]

    for idx, check in enumerate(checks, start=1):
        measured = (
            check.get("measured_elevation")
            or check.get("measured_el")
            or check.get("measured_value")
        )

        diff = (
            check.get("difference_ft")
            or check.get("difference")
            or check.get("diff")
        )

        target = (
            check.get("target_elevation")
            or check.get("target_el")
            or check.get("target_value")
        )

        tolerance = (
            check.get("tolerance_ft")
            or check.get("tolerance")
        )

        data.append(
            [
                str(idx),
                _safe(check.get("printed_label") or check.get("label") or check.get("text")),
                _safe(target),
                _safe(measured),
                _safe(diff),
                _safe(tolerance),
                _safe(check.get("status")),
                Paragraph(
                    "" if check.get("status") == "PASS" else _safe(check.get("reason"), ""),
                    styles["SmallBody"],
                ),
            ]
        )

    table = Table(
        data,
        repeatRows=1,
        colWidths=[
            0.35 * inch,
            1.0 * inch,
            0.8 * inch,
            0.9 * inch,
            0.65 * inch,
            0.55 * inch,
            0.7 * inch,
            2.0 * inch,
        ],
    )

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]

    for row_index, check in enumerate(checks, start=1):
        style.append(("TEXTCOLOR", (6, row_index), (6, row_index), _status_color(check.get("status", ""))))

    table.setStyle(TableStyle(style))
    return table


def _format_basic_issue(issue: Any, styles):
    if not isinstance(issue, dict):
        return Paragraph(f"- {_safe(issue)}", styles["BodyText"])

    issue_text = issue.get("issue", "Unknown issue")
    severity = issue.get("severity", "N/A")
    category = issue.get("category", "N/A")
    reason = issue.get("reason", "N/A")
    suggested_fix = issue.get("suggested_fix", "N/A")

    html = (
        f"<b>Issue:</b> {_safe(issue_text)}<br/>"
        f"<b>Severity:</b> {_safe(severity)} | <b>Category:</b> {_safe(category)}<br/>"
        f"<b>Reason:</b> {_safe(reason)}<br/>"
        f"<b>Suggested fix:</b> {_safe(suggested_fix)}"
    )

    return Paragraph(html, styles["BodyText"])


def _page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(
        0.7 * inch,
        0.4 * inch,
        "Automated QC supports, but does not replace, review by a qualified engineer.",
    )
    canvas.drawRightString(7.8 * inch, 0.4 * inch, f"Page {doc.page}")
    canvas.restoreState()


def write_single_section_report_pdf(
    result: dict[str, Any],
    output_pdf: str | Path,
) -> str:
    output_pdf = Path(output_pdf)
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="SmallBody",
            parent=styles["BodyText"],
            fontSize=7,
            leading=9,
        )
    )

    styles.add(
        ParagraphStyle(
            name="Warning",
            parent=styles["BodyText"],
            textColor=colors.HexColor("#7a4d00"),
            backColor=colors.HexColor("#fff4d6"),
            borderColor=colors.HexColor("#f2c94c"),
            borderWidth=0.5,
            borderPadding=6,
            spaceAfter=12,
        )
    )

    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=LETTER,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.65 * inch,
    )

    story = []

    story.append(Paragraph("Single Cross-Section Engineering QC Report", styles["Title"]))
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph(f"<b>Input PDF:</b> {_safe(result.get('input_pdf'))}", styles["BodyText"]))
    story.append(Paragraph(f"<b>Run folder:</b> {_safe(result.get('run_dir'))}", styles["BodyText"]))
    story.append(Paragraph(f"<b>Total pages analyzed:</b> {_safe(result.get('total_pages'))}", styles["BodyText"]))
    story.append(Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["BodyText"]))
    story.append(Spacer(1, 0.15 * inch))

    story.append(
        Paragraph(
            "<b>Engineering Safety Note:</b> This automated review supports, but does not replace, review by a qualified engineer. "
            "Items marked REVIEW require human judgment. Items marked FLAG indicate a confident mismatch or issue found by the automated checks.",
            styles["Warning"],
        )
    )

    summary = result.get("summary", {})

    story.append(Paragraph("Overall Summary", styles["Heading1"]))
    story.append(_status_table(summary.get("page_statuses", {}), "Pages"))
    story.append(Spacer(1, 0.12 * inch))
    story.append(_status_table(summary.get("slope_checks", {}), "Slope Checks"))
    story.append(Spacer(1, 0.12 * inch))
    story.append(_status_table(summary.get("elevation_checks", {}), "Elevation Checks"))

    story.append(PageBreak())

    pages = result.get("pages", [])

    for page_index, page in enumerate(pages):
        page_number = page.get("page_number")
        status = page.get("status", "REVIEW")

        story.append(Paragraph(f"Page {page_number} Summary - {status}", styles["Heading1"]))

        page_summary = page.get("summary", {})

        story.append(_status_table(page_summary.get("slope_checks", {}), "Slope Checks"))
        story.append(Spacer(1, 0.1 * inch))
        story.append(_status_table(page_summary.get("elevation_checks", {}), "Elevation Checks"))
        story.append(Spacer(1, 0.2 * inch))

        basic_issues = page.get("basic_issues", [])
        if basic_issues:
            story.append(Paragraph("Basic Sheet Issues", styles["Heading2"]))
            for issue in basic_issues:
                story.append(_format_basic_issue(issue, styles))
                story.append(Spacer(1, 0.08 * inch))
            story.append(Spacer(1, 0.1 * inch))

        story.append(Paragraph(f"Page {page_number} Slope Findings", styles["Heading2"]))
        story.append(_make_slope_table(page.get("slope_checks", []), styles))

        story.append(PageBreak())

        story.append(Paragraph(f"Page {page_number} Elevation Findings", styles["Heading1"]))
        story.append(_make_elevation_table(page.get("elevation_checks", []), styles))

        if page_index != len(pages) - 1:
            story.append(PageBreak())

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)

    return str(output_pdf)
