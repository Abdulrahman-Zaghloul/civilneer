from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz


STATUS_COLORS = {
    "PASS": (0.0, 0.55, 0.18),
    "REVIEW": (0.95, 0.55, 0.0),
    "FLAG": (0.85, 0.05, 0.05),
    "FAIL": (0.85, 0.05, 0.05),
}


def _status_color(status: str):
    return STATUS_COLORS.get(str(status).upper(), (0.1, 0.1, 0.1))


def _count_statuses(checks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"PASS": 0, "REVIEW": 0, "FLAG": 0, "FAIL": 0}

    for check in checks:
        status = str(check.get("status", "")).upper()
        if status in counts:
            counts[status] += 1

    return counts


def _get_point(check: dict[str, Any]) -> fitz.Point | None:
    """
    Find the best point to mark on the drawing.
    """

    for key in ["label_center", "center", "label_point", "target_point", "measured_point"]:
        value = check.get(key)

        if not isinstance(value, dict):
            continue

        if "x" in value and "y" in value:
            return fitz.Point(float(value["x"]), float(value["y"]))

    bbox = check.get("bbox")

    if isinstance(bbox, dict):
        x_keys = ["x0", "x1"]
        y_keys = ["y0", "y1"]

        if all(key in bbox for key in x_keys + y_keys):
            return fitz.Point(
                (float(bbox["x0"]) + float(bbox["x1"])) / 2,
                (float(bbox["y0"]) + float(bbox["y1"])) / 2,
            )

    return None


def _get_elevation_measurement_point(check: dict[str, Any]) -> fitz.Point | None:
    """
    Debug marker for elevation checks.

    Draw E markers ONLY at the actual measured graph point.
    Never fall back to label_center, because that hides anchor-selection bugs.
    """

    method = str(check.get("method", ""))

    # These are not real graph measurements.
    if "label_position_fallback" in method:
        return None

    # Use only actual measurement fields.
    for key in ["intersection", "measured_point", "target_point"]:
        value = check.get(key)

        if not isinstance(value, dict):
            continue

        if "x" in value and "y" in value:
            return fitz.Point(float(value["x"]), float(value["y"]))

    return None


def _rects_overlap(a: fitz.Rect, b: fitz.Rect) -> bool:
    return not (
        a.x1 < b.x0
        or a.x0 > b.x1
        or a.y1 < b.y0
        or a.y0 > b.y1
    )


def _choose_label_rect(
    point: fitz.Point,
    text: str,
    page_rect: fitz.Rect,
    used_rects: list[fitz.Rect],
    font_size: float = 8.0,
) -> fitz.Rect:
    """
    Place compact S#/E# labels near the marker while avoiding overlap.
    """

    text_width = max(16, len(text) * font_size * 0.58)
    text_height = font_size + 4

    offsets = [
        (8, -16),
        (8, 6),
        (-text_width - 8, -16),
        (-text_width - 8, 6),
        (14, -28),
        (14, 18),
        (-text_width - 14, -28),
        (-text_width - 14, 18),
        (0, -34),
        (0, 24),
    ]

    for dx, dy in offsets:
        rect = fitz.Rect(
            point.x + dx,
            point.y + dy,
            point.x + dx + text_width,
            point.y + dy + text_height,
        )

        if rect.x0 < page_rect.x0 or rect.x1 > page_rect.x1:
            continue

        if rect.y0 < page_rect.y0 or rect.y1 > page_rect.y1:
            continue

        if any(_rects_overlap(rect, used) for used in used_rects):
            continue

        return rect

    # Fallback: still place it near the point, but keep it tiny.
    return fitz.Rect(
        point.x + 8,
        point.y - 16,
        point.x + 8 + text_width,
        point.y - 16 + text_height,
    )


def _draw_header(
    page: fitz.Page,
    page_number: int,
    page_status: str,
    slope_counts: dict[str, int],
    elevation_counts: dict[str, int],
):
    return

def _draw_legend(page: fitz.Page):
    return

def _draw_marker(
    page: fitz.Page,
    point: fitz.Point,
    marker_text: str,
    status: str,
    used_rects: list[fitz.Rect],
):
    """
    Draw a small transparent dot with a readable tiny S#/E# label underneath.

    Full details stay in the report table.
    """

    color = _status_color(status)

    # Same dot size for PASS, REVIEW, and FLAG.
    radius = 2.4

    page.draw_circle(
        point,
        radius,
        color=color,
        fill=color,
        width=0.6,
        overlay=True,
        fill_opacity=0.35,
        stroke_opacity=0.85,
    )

    # Draw a small white background under the dot so the label is visible.
    font_size = 7.0
    label_width = max(14, len(marker_text) * 4.5)
    label_height = 9

    label_x = point.x - (label_width / 2)
    label_y = point.y + radius + 3

    label_rect = fitz.Rect(
        label_x,
        label_y,
        label_x + label_width,
        label_y + label_height,
    )

    page.draw_rect(
        label_rect,
        color=None,
        fill=(1, 1, 1),
        overlay=True,
        fill_opacity=0.65,
    )

    # Direct text insertion is more reliable than insert_textbox for tiny labels.
    page.insert_text(
        fitz.Point(label_x + 1.5, label_y + 7),
        marker_text,
        fontsize=font_size,
        fontname="helv",
        color=color,
        overlay=True,
    )
def _draw_page_markers(
    page: fitz.Page,
    page_result: dict[str, Any],
):
    used_rects: list[fitz.Rect] = []

    slope_checks = page_result.get("slope_checks", [])
    elevation_checks = page_result.get("elevation_checks", [])

    _draw_header(
        page=page,
        page_number=page_result.get("page_number", 1),
        page_status=page_result.get("status", "REVIEW"),
        slope_counts=_count_statuses(slope_checks),
        elevation_counts=_count_statuses(elevation_checks),
    )

    _draw_legend(page)

    for index, check in enumerate(slope_checks, start=1):
        point = _get_point(check)

        if point is None:
            continue

        _draw_marker(
            page=page,
            point=point,
            marker_text=f"S{index}",
            status=check.get("status", "REVIEW"),
            used_rects=used_rects,
        )

    for index, check in enumerate(elevation_checks, start=1):
        # For elevation debugging, draw the marker at the exact graph point
        # used for measurement, not at the EL text label.
        point = _get_elevation_measurement_point(check)

        if point is None:
            continue

        _draw_marker(
            page=page,
            point=point,
            marker_text=f"E{index}",
            status=check.get("status", "REVIEW"),
            used_rects=used_rects,
        )


def write_single_section_marked_pdf(
    result: dict[str, Any],
    input_pdf_or_output_pdf: str | Path,
    output_pdf: str | Path | None = None,
) -> str:
    """
    Write marked PDF.

    Backward compatible with old call style:
        write_single_section_marked_pdf(result, input_pdf, output_pdf)

    Also supports new call style:
        write_single_section_marked_pdf(result, output_pdf)
    """

    if output_pdf is None:
        output_pdf = input_pdf_or_output_pdf

    output_pdf = Path(output_pdf)
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    out_doc = fitz.open()

    for page_result in result.get("pages", []):
        input_page_pdf = Path(page_result.get("input_page_pdf", ""))

        if not input_page_pdf.exists():
            continue

        src_doc = fitz.open(input_page_pdf)
        out_doc.insert_pdf(src_doc, from_page=0, to_page=0)
        src_doc.close()

        page = out_doc[-1]
        _draw_page_markers(page, page_result)

    if len(out_doc) == 0:
        blank = out_doc.new_page()
        blank.insert_text(
            fitz.Point(72, 72),
            "No pages were available to mark.",
            fontsize=12,
        )

    out_doc.save(output_pdf)
    out_doc.close()

    return str(output_pdf)
