from pathlib import Path
import math
import re
import fitz


POINTS_PER_INCH = 72.0


def extract_scales_from_text(text: str) -> dict:
    """
    Extract horizontal/vertical scales from sheet text.

    Examples:
    1" = 20' Horizontal
    1" = 10' Vertical
    HORIZONTAL 1"=20'
    VERTICAL 1"=10'
    """

    horizontal = None
    vertical = None

    patterns = [
        re.compile(r'1\s*["”]\s*=\s*([0-9.]+)\s*[\'’]?\s*Horizontal', re.IGNORECASE),
        re.compile(r'Horizontal\s*.*?1\s*["”]\s*=\s*([0-9.]+)\s*[\'’]?', re.IGNORECASE),
    ]

    for pattern in patterns:
        match = pattern.search(text)
        if match:
            horizontal = float(match.group(1))
            break

    patterns = [
        re.compile(r'1\s*["”]\s*=\s*([0-9.]+)\s*[\'’]?\s*Vertical', re.IGNORECASE),
        re.compile(r'Vertical\s*.*?1\s*["”]\s*=\s*([0-9.]+)\s*[\'’]?', re.IGNORECASE),
    ]

    for pattern in patterns:
        match = pattern.search(text)
        if match:
            vertical = float(match.group(1))
            break

    # Testing fallback for common cross-section sheets.
    # Later we should make this user-configurable.
    if horizontal is None:
        horizontal = 20.0

    if vertical is None:
        vertical = 10.0

    return {
        "horizontal_ft_per_inch": horizontal,
        "vertical_ft_per_inch": vertical,
    }


def point_to_xy(point):
    """
    PyMuPDF drawing items may store coordinates as fitz.Point objects,
    tuples, lists, or Rects.
    """

    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)

    if isinstance(point, (tuple, list)) and len(point) >= 2:
        return float(point[0]), float(point[1])

    raise ValueError(f"Unsupported point format: {point}")


def rect_to_lines(rect):
    if hasattr(rect, "x0"):
        x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
    else:
        x0, y0, x1, y1 = map(float, rect[:4])

    return [
        (x0, y0, x1, y0),
        (x1, y0, x1, y1),
        (x1, y1, x0, y1),
        (x0, y1, x0, y0),
    ]


def add_line(lines, x1, y1, x2, y2, page_number):
    length = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    if length < 0.5:
        return

    lines.append(
        {
            "page_number": page_number,
            "x1": float(x1),
            "y1": float(y1),
            "x2": float(x2),
            "y2": float(y2),
            "length_points": length,
        }
    )


def extract_vector_lines(pdf_path: str) -> list[dict]:
    """
    Extract vector line segments from a PDF.

    Handles PyMuPDF drawing items:
    - l = line
    - re = rectangle
    - qu = quadrilateral
    - c = bezier curve, approximated as a chord for now
    """

    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    lines = []

    for page_index, page in enumerate(doc):
        drawings = page.get_drawings()

        for drawing in drawings:
            items = drawing.get("items", [])

            for item in items:
                if not item:
                    continue

                op = item[0]

                try:
                    if op == "l":
                        x1, y1 = point_to_xy(item[1])
                        x2, y2 = point_to_xy(item[2])
                        add_line(lines, x1, y1, x2, y2, page_index + 1)

                    elif op == "re":
                        for x1, y1, x2, y2 in rect_to_lines(item[1]):
                            add_line(lines, x1, y1, x2, y2, page_index + 1)

                    elif op == "qu":
                        # Quad has 4 corner points. Convert to 4 edges.
                        quad = item[1]
                        points = []

                        for attr in ["ul", "ur", "lr", "ll"]:
                            if hasattr(quad, attr):
                                points.append(point_to_xy(getattr(quad, attr)))

                        if len(points) == 4:
                            for i in range(4):
                                x1, y1 = points[i]
                                x2, y2 = points[(i + 1) % 4]
                                add_line(lines, x1, y1, x2, y2, page_index + 1)

                    elif op == "c":
                        # Curve item: approximate using first and last control points.
                        # This is not perfect, but it prevents losing all curved profile geometry.
                        x1, y1 = point_to_xy(item[1])
                        x2, y2 = point_to_xy(item[-1])
                        add_line(lines, x1, y1, x2, y2, page_index + 1)

                except Exception:
                    # Skip unsupported drawing fragments instead of crashing.
                    continue

    doc.close()

    for idx, line in enumerate(lines, start=1):
        line["line_id"] = idx

    return lines


def calculate_line_engineering_geometry(line: dict, scales: dict) -> dict:
    horizontal_ft_per_point = scales["horizontal_ft_per_inch"] / POINTS_PER_INCH
    vertical_ft_per_point = scales["vertical_ft_per_inch"] / POINTS_PER_INCH

    dx_points = line["x2"] - line["x1"]
    dy_points = line["y2"] - line["y1"]

    horizontal_run_ft = dx_points * horizontal_ft_per_point

    # PDF y increases downward, engineering elevation increases upward.
    vertical_rise_ft = -dy_points * vertical_ft_per_point

    abs_horizontal_run_ft = abs(horizontal_run_ft)
    abs_vertical_rise_ft = abs(vertical_rise_ft)

    if abs_horizontal_run_ft == 0:
        slope_decimal = None
        slope_percent = None
    else:
        slope_decimal = vertical_rise_ft / abs_horizontal_run_ft
        slope_percent = slope_decimal * 100

    return {
        "line_id": line["line_id"],
        "page_number": line["page_number"],
        "pdf_coordinates": {
            "x1": line["x1"],
            "y1": line["y1"],
            "x2": line["x2"],
            "y2": line["y2"],
        },
        "length_points": line["length_points"],

        # Compatibility field names.
        "horizontal_run_ft": horizontal_run_ft,
        "vertical_rise_ft": vertical_rise_ft,
        "abs_horizontal_run_ft": abs_horizontal_run_ft,
        "abs_vertical_rise_ft": abs_vertical_rise_ft,

        # Newer/simple field names used by reports/checks.
        "run_ft": abs_horizontal_run_ft,
        "rise_ft": vertical_rise_ft,

        "slope_decimal": slope_decimal,
        "slope_percent": slope_percent,
    }


def is_candidate_slope_line(measured_line: dict) -> bool:
    """
    Keep likely cross-section design/profile slope segments.
    Reject tiny text fragments, grid lines, borders, and vertical lines.
    """

    run_ft = measured_line["abs_horizontal_run_ft"]
    rise_ft = abs(measured_line["vertical_rise_ft"])
    slope = measured_line["slope_decimal"]
    length_points = measured_line["length_points"]

    if slope is None:
        return False

    # Remove tiny text fragments.
    if length_points < 4:
        return False

    # Remove very long grid/border lines.
    if length_points > 350:
        return False

    # Need some meaningful horizontal run.
    if run_ft < 0.5:
        return False

    # Avoid nearly perfectly horizontal grid lines.
    # But keep 0.02/0.03 cross-section slopes.
    if rise_ft < 0.02:
        return False

    # Keep reasonable engineering slopes.
    if abs(slope) > 1.5:
        return False

    return True


def candidate_line_signature(line: dict, precision: int = 3) -> tuple | None:
    """
    Create a stable signature for a measured line so duplicate extracted
    geometry can be removed from the candidate slope list.
    """

    coords = line.get("pdf_coordinates")

    if not isinstance(coords, dict):
        return None

    required = ["x1", "y1", "x2", "y2"]

    if not all(key in coords for key in required):
        return None

    p1 = (
        round(float(coords["x1"]), precision),
        round(float(coords["y1"]), precision),
    )

    p2 = (
        round(float(coords["x2"]), precision),
        round(float(coords["y2"]), precision),
    )

    # Normalize direction so A->B and B->A count as the same segment.
    ordered_points = tuple(sorted([p1, p2]))

    slope = line.get("slope_decimal")

    if slope is None:
        rounded_slope = None
    else:
        rounded_slope = round(abs(float(slope)), precision)

    return ordered_points + (rounded_slope,)


def deduplicate_candidate_slope_lines(candidate_lines: list[dict]) -> tuple[list[dict], dict]:
    """
    Remove duplicate candidate slope lines while preserving first occurrence.

    Returns:
        unique lines, cleanup stats
    """

    seen = set()
    unique_lines = []
    duplicate_count = 0

    for line in candidate_lines:
        signature = candidate_line_signature(line)

        if signature is None:
            unique_lines.append(line)
            continue

        if signature in seen:
            duplicate_count += 1
            continue

        seen.add(signature)
        unique_lines.append(line)

    stats = {
        "raw_candidate_slope_lines": len(candidate_lines),
        "unique_candidate_slope_lines": len(unique_lines),
        "duplicate_candidate_slope_lines_removed": duplicate_count,
    }

    return unique_lines, stats


def clean_candidate_slope_lines(measured_lines: list[dict]) -> tuple[list[dict], dict]:
    """
    Apply candidate filtering and lightweight cleanup before slope matching.
    """

    raw_candidate_lines = [
        line for line in measured_lines
        if is_candidate_slope_line(line)
    ]

    unique_candidate_lines, dedupe_stats = deduplicate_candidate_slope_lines(
        raw_candidate_lines
    )

    cleanup_stats = {
        "total_measured_lines": len(measured_lines),
        **dedupe_stats,
    }

    return unique_candidate_lines, cleanup_stats


def build_geometry_report(pdf_path: str, text: str) -> dict:
    scales = extract_scales_from_text(text)
    vector_lines = extract_vector_lines(pdf_path)

    measured_lines = [
        calculate_line_engineering_geometry(line, scales)
        for line in vector_lines
    ]

    candidate_slope_lines, cleanup_stats = clean_candidate_slope_lines(
        measured_lines
    )

    return {
        "input_pdf": pdf_path,
        "scales": scales,
        "total_vector_lines": len(vector_lines),
        "total_measured_lines": len(measured_lines),
        "total_candidate_slope_lines": len(candidate_slope_lines),
        "geometry_cleanup": cleanup_stats,
        "measured_lines": measured_lines,
        "candidate_slope_lines": candidate_slope_lines,
    }
