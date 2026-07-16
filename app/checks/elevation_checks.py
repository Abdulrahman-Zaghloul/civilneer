import math
import re
from pathlib import Path

import fitz

from app.geometry_extractor import extract_vector_lines
from app.elevation_label_extractor import clean_text



def median(values: list[float]) -> float:
    values = sorted(values)
    n = len(values)

    if n == 0:
        raise ValueError("Cannot calculate median of empty list.")

    mid = n // 2

    if n % 2 == 1:
        return values[mid]

    return (values[mid - 1] + values[mid]) / 2


def elevation_from_pdf_y(pdf_y: float, calibration: dict) -> float | None:
    if not calibration.get("is_calibrated"):
        return None

    a = calibration["elevation_per_pdf_point"]
    b = calibration["intercept"]

    return a * pdf_y + b


def expected_pdf_y_for_elevation(elevation: float, calibration: dict) -> float | None:
    if not calibration.get("is_calibrated"):
        return None

    a = calibration["elevation_per_pdf_point"]
    b = calibration["intercept"]

    if a == 0:
        return None

    return (elevation - b) / a


def line_length(line: dict) -> float:
    return math.sqrt(
        (line["x2"] - line["x1"]) ** 2 +
        (line["y2"] - line["y1"]) ** 2
    )


def is_near_vertical(line: dict, max_dx: float = 3.0, min_dy: float = 12.0) -> bool:
    dx = abs(line["x2"] - line["x1"])
    dy = abs(line["y2"] - line["y1"])
    return dx <= max_dx and dy >= min_dy


def is_reasonable_design_line(line: dict) -> bool:
    """
    Keep likely engineering geometry.
    Reject tiny fragments, grid lines, borders, and vertical callout lines.
    """

    length = line_length(line)
    dx = abs(line["x2"] - line["x1"])
    dy = abs(line["y2"] - line["y1"])

    if length < 4:
        return False

    # Very long horizontal lines are usually grid/border lines.
    if length > 260:
        return False

    # Skip vertical lines for feature elevation measurement.
    if dx < 2 and dy > 8:
        return False

    return True


def same_line(a: dict, b: dict, tolerance: float = 0.5) -> bool:
    return (
        abs(a["x1"] - b["x1"]) <= tolerance and
        abs(a["y1"] - b["y1"]) <= tolerance and
        abs(a["x2"] - b["x2"]) <= tolerance and
        abs(a["y2"] - b["y2"]) <= tolerance
    )


def project_point_to_segment(px: float, py: float, line: dict) -> dict:
    """
    Project a point onto a line segment and return the nearest point on that segment.
    """

    x1 = line["x1"]
    y1 = line["y1"]
    x2 = line["x2"]
    y2 = line["y2"]

    dx = x2 - x1
    dy = y2 - y1

    length_squared = dx * dx + dy * dy

    if length_squared == 0:
        nearest_x = x1
        nearest_y = y1
    else:
        t = ((px - x1) * dx + (py - y1) * dy) / length_squared
        t = max(0, min(1, t))

        nearest_x = x1 + t * dx
        nearest_y = y1 + t * dy

    distance = math.sqrt((px - nearest_x) ** 2 + (py - nearest_y) ** 2)

    return {
        "x": nearest_x,
        "y": nearest_y,
        "distance_points": distance,
    }


def find_horizontal_callout_feature_point(
    label: dict,
    vector_lines: list[dict],
    max_distance_points: float = 40.0,
) -> dict | None:
    """
    For horizontal labels like TOB EL. 13.60 or BTM EL. 9.00,
    find the nearby design geometry line being labeled.

    This is different from vertical EL callouts.
    TOB/BTM labels often sit beside or above the feature line without a leader.
    """

    label_x = label["center"]["x"]
    label_y = label["center"]["y"]

    candidates = []

    for line in vector_lines:
        if not is_reasonable_design_line(line):
            continue

        projected = project_point_to_segment(label_x, label_y, line)

        if projected["distance_points"] > max_distance_points:
            continue

        # Prefer lines that are close to the label and not tiny fragments.
        length = line_length(line)

        score = projected["distance_points"]

        # Slightly prefer longer real geometry over tiny pieces.
        if length > 20:
            score -= 2

        candidates.append(
            {
                "target_line": line,
                "intersection": {
                    "x": projected["x"],
                    "y": projected["y"],
                },
                "distance_to_label_points": projected["distance_points"],
                "score": score,
            }
        )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item["score"])

    # Keep a compact debug ranking so the downloadable debug JSON explains
    # why the chosen elevation anchor won.
    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index

    best_candidate = candidates[0]
    best_candidate["candidate_ranking"] = [
        {
            "rank": candidate.get("rank"),
            "intersection": candidate.get("intersection"),
            "distance_to_leader_points": candidate.get("distance_to_leader_points"),
            "measured_elevation": candidate.get("measured_elevation"),
            "elevation_difference": candidate.get("elevation_difference"),
            "expected_y_distance": candidate.get("expected_y_distance"),
            "score": candidate.get("score"),
            "target_line": candidate.get("target_line"),
        }
        for candidate in candidates[:10]
    ]

    return best_candidate


def find_adjacent_leader_line(label: dict, vector_lines: list[dict]) -> dict | None:
    """
    Find the vertical black leader/callout line beside regular EL labels.
    """

    label_x = label["center"]["x"]
    label_y = label["center"]["y"]

    candidates = []

    for line in vector_lines:
        if not is_near_vertical(line):
            continue

        length = line_length(line)

        # Ignore very long grid/structure/border lines.
        if length > 140:
            continue

        x_mid = (line["x1"] + line["x2"]) / 2
        y_mid = (line["y1"] + line["y2"]) / 2
        y_min = min(line["y1"], line["y2"])
        y_max = max(line["y1"], line["y2"])

        horizontal_gap = abs(x_mid - label_x)

        if horizontal_gap > 45:
            continue

        if label_y < y_min - 80 or label_y > y_max + 80:
            continue

        score = horizontal_gap + abs(y_mid - label_y) * 0.25

        candidates.append(
            {
                "line": line,
                "score": score,
                "horizontal_gap": horizontal_gap,
                "length": length,
            }
        )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item["score"])
    return candidates[0]["line"]


def vertical_line_intersection_y(x: float, line: dict) -> float | None:
    x1 = line["x1"]
    y1 = line["y1"]
    x2 = line["x2"]
    y2 = line["y2"]

    dx = x2 - x1

    if abs(dx) < 0.0001:
        return None

    min_x = min(x1, x2)
    max_x = max(x1, x2)

    if x < min_x - 1.0 or x > max_x + 1.0:
        return None

    t = (x - x1) / dx

    if t < -0.05 or t > 1.05:
        return None

    return y1 + t * (y2 - y1)



def is_likely_grid_line_for_elevation_anchor(line: dict) -> bool:
    """
    Reject likely grid/border lines when searching for elevation anchors.

    Long perfectly horizontal lines are usually grid rows, not the actual
    feature being called out by an EL label.
    """

    length = line_length(line)
    dx = abs(line["x2"] - line["x1"])
    dy = abs(line["y2"] - line["y1"])

    if dy <= 1.0 and length >= 80:
        return True

    if dx <= 1.0 and length >= 80:
        return True

    return False


def find_target_y_rescue_anchor(
    label: dict,
    vector_lines: list[dict],
    calibration: dict,
    leader_line: dict | None = None,
    max_x_distance_points: float = 80.0,
) -> dict | None:
    """
    Rescue strategy for EL callouts.

    If the leader intersection picks a bad line, use the calibrated grid to
    compute where the printed elevation should be, then search nearby geometry
    around that expected y-coordinate.
    """

    if not calibration.get("is_calibrated"):
        return None

    expected_y = expected_pdf_y_for_elevation(label["elevation"], calibration)

    if expected_y is None:
        return None

    label_x = label["center"]["x"]

    if leader_line:
        reference_x = (leader_line["x1"] + leader_line["x2"]) / 2
    else:
        reference_x = label_x

    minor_spacing = calibration.get("minor_grid_spacing_points") or 8.0
    max_y_distance_points = max(2.5, minor_spacing * 0.45)

    candidates = []

    for line in vector_lines:
        if not is_reasonable_design_line(line):
            continue

        if leader_line and same_line(line, leader_line):
            continue

        if is_likely_grid_line_for_elevation_anchor(line):
            continue

        projected = project_point_to_segment(reference_x, expected_y, line)

        y_distance = abs(projected["y"] - expected_y)
        x_distance = abs(projected["x"] - reference_x)

        if y_distance > max_y_distance_points:
            continue

        if x_distance > max_x_distance_points:
            continue

        measured_elevation = elevation_from_pdf_y(projected["y"], calibration)

        if measured_elevation is None:
            continue

        elevation_difference = abs(measured_elevation - label["elevation"])

        # Prefer elevation closeness first, then x distance, then real line length.
        length = line_length(line)

        score = (
            elevation_difference * 100.0
            + y_distance * 5.0
            + x_distance * 0.10
        )

        if length < 6:
            score += 10

        candidates.append(
            {
                "intersection": {
                    "x": projected["x"],
                    "y": projected["y"],
                },
                "target_line": line,
                "distance_to_leader_points": projected["distance_points"],
                "measured_elevation": measured_elevation,
                "elevation_difference": elevation_difference,
                "expected_y_distance": y_distance,
                "score": score,
                "method": "target_y_rescue_anchor",
            }
        )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item["score"])

    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index

    best_candidate = candidates[0]
    best_candidate["candidate_ranking"] = [
        {
            "rank": candidate.get("rank"),
            "intersection": candidate.get("intersection"),
            "distance_to_leader_points": candidate.get("distance_to_leader_points"),
            "measured_elevation": candidate.get("measured_elevation"),
            "elevation_difference": candidate.get("elevation_difference"),
            "expected_y_distance": candidate.get("expected_y_distance"),
            "score": candidate.get("score"),
            "target_line": candidate.get("target_line"),
        }
        for candidate in candidates[:12]
    ]

    return best_candidate



def find_leader_geometry_intersection(
    leader_line: dict,
    vector_lines: list[dict],
    label: dict | None = None,
    calibration: dict | None = None,
) -> dict | None:
    """
    Extend the vertical leader line until it intersects nearby design geometry.

    Elevation Resolver v2 anchor rule:
    If a printed target elevation and grid calibration are available, prefer
    the candidate intersection whose measured elevation is closest to the
    printed EL value. This prevents the app from choosing the wrong lower
    dashed/profile line just because it is geometrically nearby.
    """

    leader_x = (leader_line["x1"] + leader_line["x2"]) / 2
    leader_y_min = min(leader_line["y1"], leader_line["y2"])
    leader_y_max = max(leader_line["y1"], leader_line["y2"])

    expected_y = None

    if label is not None and calibration is not None and calibration.get("is_calibrated"):
        expected_y = expected_pdf_y_for_elevation(label["elevation"], calibration)

    candidates = []

    for line in vector_lines:
        if same_line(line, leader_line):
            continue

        if not is_reasonable_design_line(line):
            continue

        intersection_y = vertical_line_intersection_y(leader_x, line)

        if intersection_y is None:
            continue

        distance_to_leader = min(
            abs(intersection_y - leader_y_min),
            abs(intersection_y - leader_y_max),
        )

        # Keep this broader now because target elevation will guide selection.
        if distance_to_leader > 120:
            continue

        measured_elevation = None
        elevation_difference = None
        expected_y_distance = None

        if calibration is not None and calibration.get("is_calibrated"):
            measured_elevation = elevation_from_pdf_y(intersection_y, calibration)

        if measured_elevation is not None and label is not None:
            elevation_difference = abs(measured_elevation - label["elevation"])

        if expected_y is not None:
            expected_y_distance = abs(intersection_y - expected_y)

        # Scoring:
        # 1. If target elevation is known, make elevation closeness dominant.
        # 2. Use distance to leader as a secondary tiebreaker.
        # 3. Without calibration, fall back to old nearest-intersection behavior.
        if elevation_difference is not None:
            score = (elevation_difference * 100.0) + (distance_to_leader * 0.05)
        elif expected_y_distance is not None:
            score = expected_y_distance + (distance_to_leader * 0.05)
        else:
            score = distance_to_leader

        candidates.append(
            {
                "intersection": {
                    "x": leader_x,
                    "y": intersection_y,
                },
                "target_line": line,
                "distance_to_leader_points": distance_to_leader,
                "measured_elevation": measured_elevation,
                "elevation_difference": elevation_difference,
                "expected_y_distance": expected_y_distance,
                "score": score,
            }
        )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item["score"])

    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index

    best_candidate = candidates[0]

    best_candidate["candidate_ranking"] = [
        {
            "rank": candidate.get("rank"),
            "intersection": candidate.get("intersection"),
            "distance_to_leader_points": candidate.get("distance_to_leader_points"),
            "measured_elevation": candidate.get("measured_elevation"),
            "elevation_difference": candidate.get("elevation_difference"),
            "expected_y_distance": candidate.get("expected_y_distance"),
            "score": candidate.get("score"),
            "target_line": candidate.get("target_line"),
        }
        for candidate in candidates[:12]
    ]

    return best_candidate


def build_elevation_check_result(
    label: dict,
    measured_point: dict,
    target_line: dict | None,
    calibration: dict,
    method: str,
    tolerance_ft: float,
    reason_pass: str,
    reason_flag: str,
    distance_to_leader_points: float | None = None,
) -> dict:
    measured_elevation = elevation_from_pdf_y(measured_point["y"], calibration)
    difference = measured_elevation - label["elevation"]
    abs_difference = abs(difference)

    if abs_difference <= tolerance_ft:
        status = "PASS"
        reason = reason_pass
    elif abs_difference <= 0.50:
        status = "FLAG"
        reason = reason_flag
    else:
        status = "FAIL"
        reason = reason_flag

    return {
        "label_id": label["label_id"],
        "printed_label": label["text"],
        "label_type": label["label_type"],
        "target_elevation": label["elevation"],
        "measured_elevation": measured_elevation,
        "difference_ft": difference,
        "abs_difference_ft": abs_difference,
        "tolerance_ft": tolerance_ft,
        "status": status,
        "method": method,
        "reason": reason,
        "label_center": label["center"],
        "leader_line": None,
        "intersection": measured_point,
        "target_line": target_line,
        "distance_to_leader_points": distance_to_leader_points,
    }


def validate_elevation_label_occurrences(
    elevation_labels: list[dict],
    calibration: dict,
    pdf_path: str | None = None,
    tolerance_ft: float = 0.15,
    fallback_tolerance_ft: float = 3.0,
) -> list[dict]:
    """
    Validate each elevation label.

    Methods:
    1. TOB/BTM horizontal callout:
       Use nearest nearby design geometry line.

    2. Regular EL vertical leader:
       Use leader-line intersection.

    3. Fallback:
       Use text position only.
    """

    vector_lines = extract_vector_lines(pdf_path) if pdf_path else []
    checks = []

    for label in elevation_labels:
        if not calibration.get("is_calibrated"):
            checks.append(
                {
                    "label_id": label["label_id"],
                    "printed_label": label["text"],
                    "label_type": label["label_type"],
                    "target_elevation": label["elevation"],
                    "status": "REVIEW",
                    "method": "none",
                    "reason": "Elevation grid calibration was not confident enough to verify this elevation label.",
                    "measured_elevation": None,
                    "difference_ft": None,
                    "label_center": label["center"],
                    "leader_line": None,
                    "intersection": None,
                    "target_line": None,
                }
            )
            continue

        # Horizontal TOB/BTM labels should be measured from nearby geometry,
        # not from the text position.
        if label["label_type"] in ["TOB", "BTM"]:
            horizontal_feature = find_horizontal_callout_feature_point(
                label,
                vector_lines,
            )

            if horizontal_feature:
                check = build_elevation_check_result(
                    label=label,
                    measured_point=horizontal_feature["intersection"],
                    target_line=horizontal_feature["target_line"],
                    calibration=calibration,
                    method="horizontal_callout_nearest_geometry",
                    tolerance_ft=tolerance_ft,
                    reason_pass="Printed TOB/BTM elevation matches the nearby labeled geometry.",
                    reason_flag="Printed TOB/BTM elevation differs from the nearby labeled geometry. Review manually.",
                    distance_to_leader_points=horizontal_feature["distance_to_label_points"],
                )
                checks.append(check)
                continue

        # Regular EL labels usually use vertical leader lines.
        leader_line = find_adjacent_leader_line(label, vector_lines) if vector_lines else None
        intersection_result = None

        if leader_line:
            intersection_result = find_leader_geometry_intersection(
                leader_line,
                vector_lines,
                label=label,
                calibration=calibration,
            )

        if leader_line and intersection_result:
            measured_point = intersection_result["intersection"]

            measured_elevation = elevation_from_pdf_y(measured_point["y"], calibration)
            difference = measured_elevation - label["elevation"]
            abs_difference = abs(difference)

            # If the leader intersection is far from the printed EL value,
            # try a calibrated target-y rescue before calling it wrong.
            if abs_difference > 0.75:
                rescue_result = find_target_y_rescue_anchor(
                    label=label,
                    vector_lines=vector_lines,
                    calibration=calibration,
                    leader_line=leader_line,
                )

                if rescue_result:
                    rescue_point = rescue_result["intersection"]
                    rescue_measured = elevation_from_pdf_y(rescue_point["y"], calibration)
                    rescue_difference = rescue_measured - label["elevation"]
                    rescue_abs_difference = abs(rescue_difference)

                    if rescue_abs_difference < abs_difference:
                        intersection_result = rescue_result
                        measured_point = rescue_point
                        measured_elevation = rescue_measured
                        difference = rescue_difference
                        abs_difference = rescue_abs_difference

            if abs_difference <= tolerance_ft:
                status = "PASS"
                reason = "Printed elevation matches the measured elevation at the leader-line geometry intersection."
            elif abs_difference <= 0.50:
                status = "FLAG"
                reason = "Printed elevation is close, but the leader-line intersection differs more than the preferred tolerance."
            else:
                status = "FAIL"
                reason = "Printed elevation does not match the measured elevation at the leader-line geometry intersection."

            checks.append(
                {
                    "label_id": label["label_id"],
                    "printed_label": label["text"],
                    "label_type": label["label_type"],
                    "target_elevation": label["elevation"],
                    "measured_elevation": measured_elevation,
                    "difference_ft": difference,
                    "abs_difference_ft": abs_difference,
                    "tolerance_ft": tolerance_ft,
                    "status": status,
                    "method": "leader_intersection",
                    "reason": reason,
                    "label_center": label["center"],
                    "leader_line": leader_line,
                    "intersection": measured_point,
                    "target_line": intersection_result["target_line"],
                    "distance_to_leader_points": intersection_result["distance_to_leader_points"],
                    "candidate_ranking": intersection_result.get("candidate_ranking", []),
                    "anchor_selection_score": intersection_result.get("score"),
                    "anchor_elevation_difference": intersection_result.get("elevation_difference"),
                    "anchor_expected_y_distance": intersection_result.get("expected_y_distance"),
                }
            )
            continue

        # Final fallback: text position only.
        estimated_elevation = elevation_from_pdf_y(label["center"]["y"], calibration)
        difference = estimated_elevation - label["elevation"]
        abs_difference = abs(difference)

        if abs_difference <= fallback_tolerance_ft:
            status = "PASS"
            reason = (
                "No geometry reference was found, so the label location was used as fallback. "
                "This is less reliable than a geometry-based check."
            )
        else:
            status = "FLAG"
            reason = (
                "No geometry reference was found, and the label location does not closely match "
                "the printed elevation. Review manually."
            )

        checks.append(
            {
                "label_id": label["label_id"],
                "printed_label": label["text"],
                "label_type": label["label_type"],
                "target_elevation": label["elevation"],
                "measured_elevation": estimated_elevation,
                "difference_ft": difference,
                "abs_difference_ft": abs_difference,
                "tolerance_ft": fallback_tolerance_ft,
                "status": status,
                "method": "label_position_fallback_review",
                "reason": reason,
                "label_center": label["center"],
                "leader_line": None,
                "intersection": None,
                "target_line": None,
                "distance_to_leader_points": None,
            }
        )

    return checks




def linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """
    Fit y = a*x + b.

    x = PDF y-coordinate
    y = engineering elevation
    """

    n = len(xs)

    if n < 2:
        raise ValueError("At least two points are required for calibration.")

    x_mean = sum(xs) / n
    y_mean = sum(ys) / n

    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)

    if denominator == 0:
        raise ValueError("Cannot calibrate elevation grid because PDF y-values are identical.")

    a = numerator / denominator
    b = y_mean - a * x_mean

    return a, b


def build_elevation_grid_calibration(pdf_path: str) -> dict:
    """
    Elevation Resolver v2b.

    Detects horizontal grid rows even when the PDF breaks each grid line
    into many short vector segments.

    Supports:
    - 2+ printed elevation grid labels
    - 1 printed elevation grid label plus repeated minor grid spacing
    """

    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    page = doc[0]
    page_width = page.rect.width
    page_height = page.rect.height

    words = page.get_text("words")
    page_text = page.get_text()

    # Use printed EL labels to constrain valid elevation grid numbers.
    # Example: if the sheet has EL. 39.68 and EL. 37.94, valid grid numbers
    # are likely around 20-60, not bottom offset labels like 120 or 140.
    target_elevations = []

    # Standard format: EL. 39.68
    for match in re.finditer(r"\bEL\.?\s*([0-9]+(?:\.[0-9]+)?)", page_text, re.IGNORECASE):
        try:
            target_elevations.append(float(match.group(1)))
        except ValueError:
            pass

    # Reversed/split format sometimes extracted as: 39.68' EL.
    for match in re.finditer(r"\b([0-9]+(?:\.[0-9]+)?)\s*'?\s*EL\.?\b", page_text, re.IGNORECASE):
        try:
            target_elevations.append(float(match.group(1)))
        except ValueError:
            pass

    target_elevations = sorted(set(target_elevations))

    vector_lines = extract_vector_lines(pdf_path)

    horizontal_segments = []

    for line in vector_lines:
        x1 = line["x1"]
        y1 = line["y1"]
        x2 = line["x2"]
        y2 = line["y2"]

        dx = abs(x2 - x1)
        dy = abs(y2 - y1)

        if dy > 1.75:
            continue

        if dx < 8.0:
            continue

        y = (y1 + y2) / 2

        if y < page_height * 0.04 or y > page_height * 0.96:
            continue

        horizontal_segments.append(
            {
                "x1": min(x1, x2),
                "x2": max(x1, x2),
                "y": y,
                "length": dx,
            }
        )

    row_clusters = []

    for segment in sorted(horizontal_segments, key=lambda item: item["y"]):
        placed = False

        for cluster in row_clusters:
            cluster_y = median([item["y"] for item in cluster])

            if abs(segment["y"] - cluster_y) <= 2.0:
                cluster.append(segment)
                placed = True
                break

        if not placed:
            row_clusters.append([segment])

    grid_rows = []

    for cluster in row_clusters:
        row_y = median([item["y"] for item in cluster])
        total_segment_length = sum(item["length"] for item in cluster)
        min_x = min(item["x1"] for item in cluster)
        max_x = max(item["x2"] for item in cluster)
        span = max_x - min_x

        if total_segment_length < page_width * 0.18 and span < page_width * 0.25:
            continue

        grid_rows.append(
            {
                "y": row_y,
                "total_segment_length": total_segment_length,
                "span": span,
                "min_x": min_x,
                "max_x": max_x,
                "segment_count": len(cluster),
            }
        )

    grid_rows = sorted(grid_rows, key=lambda item: item["y"])
    grid_y_values = [row["y"] for row in grid_rows]

    grid_diffs = [
        grid_y_values[index + 1] - grid_y_values[index]
        for index in range(len(grid_y_values) - 1)
    ]

    useful_grid_diffs = [
        diff for diff in grid_diffs
        if 2.0 <= diff <= 40.0
    ]

    minor_grid_spacing_points = median(useful_grid_diffs) if useful_grid_diffs else None

    label_candidates_by_value = {}

    if grid_rows:
        grid_left_x = median([row["min_x"] for row in grid_rows])
        grid_right_x = median([row["max_x"] for row in grid_rows])
        grid_top_y = min(grid_y_values)
        grid_bottom_y = max(grid_y_values)
    else:
        grid_left_x = page_width * 0.15
        grid_right_x = page_width * 0.85
        grid_top_y = page_height * 0.05
        grid_bottom_y = page_height * 0.95

    grid_edge_tolerance = max(70.0, page_width * 0.10)

    for word in words:
        x0, y0, x1, y1, raw_text, block_no, line_no, word_no = word
        cleaned = clean_text(raw_text)

        if not cleaned.isdigit():
            continue

        value = int(cleaned)

        if value < 10 or value > 200:
            continue

        # If EL labels exist, reject grid-number candidates far away from
        # the target elevation range. This prevents offset labels like 120/140
        # from becoming fake elevation grid ticks.
        if target_elevations:
            min_allowed_grid = max(0.0, min(target_elevations) - 12.0)
            max_allowed_grid = max(target_elevations) + 12.0

            if value < min_allowed_grid or value > max_allowed_grid:
                continue

        center_x = (x0 + x1) / 2
        center_y = (y0 + y1) / 2

        near_grid_left = abs(center_x - grid_left_x) <= grid_edge_tolerance
        near_grid_right = abs(center_x - grid_right_x) <= grid_edge_tolerance

        if not (near_grid_left or near_grid_right):
            continue

        if center_y < grid_top_y - 30 or center_y > grid_bottom_y + 6:
            continue

        label_candidates_by_value.setdefault(value, []).append(
            {
                "value": value,
                "text_center_x": center_x,
                "text_center_y": center_y,
                "bbox": {
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                },
            }
        )

    ticks_by_value = {}

    for value, label_candidates in label_candidates_by_value.items():
        matched_grid_ys = []

        for label in label_candidates:
            text_y = label["text_center_y"]

            if not grid_y_values:
                continue

            nearest_grid_y = min(
                grid_y_values,
                key=lambda grid_y: abs(grid_y - text_y),
            )

            allowed_distance = 16.0

            if minor_grid_spacing_points:
                allowed_distance = max(16.0, minor_grid_spacing_points * 0.85)

            if abs(nearest_grid_y - text_y) <= allowed_distance:
                matched_grid_ys.append(nearest_grid_y)

        if matched_grid_ys:
            ticks_by_value[value] = {
                "elevation": float(value),
                "pdf_y": median(matched_grid_ys),
                "matched_grid_ys": matched_grid_ys,
                "count": len(matched_grid_ys),
            }

    ticks = sorted(ticks_by_value.values(), key=lambda item: item["elevation"])

    # Filter false grid labels.
    # In PDF coordinates, y increases downward.
    # In engineering coordinates, elevation increases upward.
    # Therefore, as elevation increases, pdf_y should decrease.
    #
    # Example of valid ticks:
    # 10 -> y 341
    # 20 -> y 259
    # 30 -> y 176
    # 40 -> y 94
    #
    # False bottom offset labels like 120/140 often appear near the bottom
    # and break this monotonic relationship, so remove them.
    monotonic_ticks = []

    for tick in ticks:
        if not monotonic_ticks:
            monotonic_ticks.append(tick)
            continue

        previous_tick = monotonic_ticks[-1]

        elevation_increases = tick["elevation"] > previous_tick["elevation"]
        pdf_y_moves_up = tick["pdf_y"] < previous_tick["pdf_y"] - 2.0

        if elevation_increases and pdf_y_moves_up:
            monotonic_ticks.append(tick)

    if len(monotonic_ticks) >= 2:
        ticks = monotonic_ticks

    if len(ticks) >= 2:
        pdf_y_values = [tick["pdf_y"] for tick in ticks]
        elevation_values = [tick["elevation"] for tick in ticks]

        a, b = linear_regression(pdf_y_values, elevation_values)

        doc.close()

        return {
            "is_calibrated": True,
            "method": "segmented_grid_major_label_calibration_v2b",
            "confidence": "high",
            "page_number": 1,
            "elevation_per_pdf_point": a,
            "intercept": b,
            "pdf_points_per_elevation_foot": abs(1 / a) if a != 0 else None,
            "minor_grid_spacing_points": minor_grid_spacing_points,
            "min_grid_elevation": min(elevation_values),
            "max_grid_elevation": max(elevation_values),
            "ticks": ticks,
            "detected_grid_y_values": grid_y_values,
            "grid_rows": grid_rows,
            "reason": "Calibrated from two or more printed grid elevation labels.",
        }

    if len(ticks) == 1 and minor_grid_spacing_points:
        tick = ticks[0]

        # PDF y increases downward, but engineering elevation decreases downward.
        a = -1.0 / minor_grid_spacing_points
        b = tick["elevation"] - (a * tick["pdf_y"])

        doc.close()

        return {
            "is_calibrated": True,
            "method": "segmented_grid_single_label_spacing_calibration_v2b",
            "confidence": "medium",
            "page_number": 1,
            "elevation_per_pdf_point": a,
            "intercept": b,
            "pdf_points_per_elevation_foot": minor_grid_spacing_points,
            "minor_grid_spacing_points": minor_grid_spacing_points,
            "min_grid_elevation": None,
            "max_grid_elevation": None,
            "ticks": ticks,
            "detected_grid_y_values": grid_y_values,
            "grid_rows": grid_rows,
            "reason": "Calibrated from one printed grid elevation label and repeated horizontal minor grid spacing.",
        }

    doc.close()

    return {
        "is_calibrated": False,
        "method": "segmented_grid_calibration_v2b",
        "confidence": "none",
        "reason": "Could not confidently detect enough grid labels or repeated horizontal grid spacing.",
        "ticks": ticks,
        "detected_grid_y_values": grid_y_values,
        "grid_rows": grid_rows,
        "minor_grid_spacing_points": minor_grid_spacing_points,
    }
