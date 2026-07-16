import math


MAX_SEGMENT_DISTANCE_POINTS = 35.0
TOP_CANDIDATE_LIMIT = 5


def line_signature(line: dict, precision: int = 3) -> tuple | None:
    """
    Create a stable signature for a PDF line so duplicate extracted segments
    can be removed before candidate ranking.
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


def deduplicate_candidate_lines(candidate_lines: list[dict]) -> list[dict]:
    """
    Remove duplicate geometry segments while preserving first occurrence.
    """

    seen = set()
    unique_lines = []

    for line in candidate_lines:
        signature = line_signature(line)

        if signature is None:
            unique_lines.append(line)
            continue

        if signature in seen:
            continue

        seen.add(signature)
        unique_lines.append(line)

    return unique_lines


def get_line_points(line: dict) -> tuple[float, float, float, float]:
    coords = line["pdf_coordinates"]
    return coords["x1"], coords["y1"], coords["x2"], coords["y2"]


def line_midpoint(line: dict) -> tuple[float, float]:
    x1, y1, x2, y2 = get_line_points(line)
    return (
        (x1 + x2) / 2,
        (y1 + y2) / 2,
    )


def distance_between_points(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def point_to_segment_distance(
    px: float,
    py: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> float:
    dx = x2 - x1
    dy = y2 - y1

    if dx == 0 and dy == 0:
        return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

    t = ((px - x1) * dx + (py - y1) * dy) / ((dx * dx) + (dy * dy))
    t = max(0, min(1, t))

    closest_x = x1 + t * dx
    closest_y = y1 + t * dy

    return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)


def is_percent_slope_label(label: dict) -> bool:
    text = str(label.get("text") or label.get("printed_label") or "")
    return "%" in text


def slope_tolerance_for_label(label: dict) -> float:
    """
    PASS tolerance for PDF-derived slope measurements.

    Percent labels:
        0.005 decimal = 0.50 percentage points.
        Example: 2.00% can pass from 1.50% to 2.50%.

    Ratio labels:
        0.01 decimal keeps ratio checks tighter.
        Example: 1:2 target is 0.50; pass range is 0.49 to 0.51.
    """
    if is_percent_slope_label(label):
        return 0.005

    return 0.01


def slope_review_tolerance_for_label(label: dict) -> float:
    """
    REVIEW band for close-but-not-pass slope measurements.

    Percent labels:
        0.01 decimal = 1.00 percentage point.

    Ratio labels:
        0.02 decimal keeps ratio checks reasonably strict.
    """
    if is_percent_slope_label(label):
        return 0.01

    return 0.02

def summarize_candidate_line(
    rank: int,
    item: dict,
    tolerance: float,
) -> dict:
    line = item["line"]
    measured_slope = abs(line.get("slope_decimal", 0))
    slope_difference = item["slope_difference"]

    return {
        "rank": rank,
        "line_id": line.get("line_id"),
        "distance_to_label_points": item["distance_points"],
        "measured_slope": measured_slope,
        "slope_difference": slope_difference,
        "within_tolerance": slope_difference <= tolerance,
        "run_ft": line.get("abs_horizontal_run_ft"),
        "rise_ft": line.get("abs_vertical_rise_ft"),
        "slope_percent": line.get("slope_percent"),
        "pdf_coordinates": line.get("pdf_coordinates"),
    }


def rank_nearby_line_candidates(
    label: dict,
    candidate_lines: list[dict],
    max_segment_distance_points: float = MAX_SEGMENT_DISTANCE_POINTS,
) -> list[dict]:
    """
    Rank nearby slope-line candidates.

    Selection priority intentionally matches current behavior:
    1. Prefer slope-compatible nearby lines.
    2. Among compatible lines, choose the closest.
    3. If none are compatible, choose the closest nearby line so it can be FLAGGED.
    """

    label_x = label["center"]["x"]
    label_y = label["center"]["y"]
    target_slope = abs(label["target_slope"])
    tolerance = slope_tolerance_for_label(label)

    ranked_candidates = []
    unique_candidate_lines = deduplicate_candidate_lines(candidate_lines)

    for line in unique_candidate_lines:
        measured_slope = line.get("slope_decimal")

        if measured_slope is None:
            continue

        x1, y1, x2, y2 = get_line_points(line)

        segment_distance = point_to_segment_distance(
            label_x,
            label_y,
            x1,
            y1,
            x2,
            y2,
        )

        if segment_distance > max_segment_distance_points:
            continue

        slope_difference = abs(abs(measured_slope) - target_slope)
        is_slope_compatible = slope_difference <= tolerance

        ranked_candidates.append(
            {
                "line": line,
                "distance_points": segment_distance,
                "slope_difference": slope_difference,
                "is_slope_compatible": is_slope_compatible,
            }
        )

    ranked_candidates.sort(
        key=lambda item: (
            not item["is_slope_compatible"],
            item["distance_points"],
            item["slope_difference"],
        )
    )

    return ranked_candidates


def find_best_nearby_line_for_label(
    label: dict,
    candidate_lines: list[dict],
    max_segment_distance_points: float = MAX_SEGMENT_DISTANCE_POINTS,
) -> dict | None:
    ranked_candidates = rank_nearby_line_candidates(
        label=label,
        candidate_lines=candidate_lines,
        max_segment_distance_points=max_segment_distance_points,
    )

    if not ranked_candidates:
        return None

    target_slope = abs(label["target_slope"])

    # Engineering selection tolerance.
    # The strict report tolerance may be tighter, but for choosing the intended
    # nearby line, we should prefer the line that best matches the printed slope.
    # This prevents a tiny nearby fragment from beating the correct line.
    slope_selection_tolerance = max(0.0065, target_slope * 0.25)

    slope_compatible_candidates = []

    for item in ranked_candidates:
        line = item.get("line", {})
        measured_slope = line.get("slope_decimal")

        if measured_slope is None:
            continue

        slope_difference = abs(abs(measured_slope) - target_slope)

        if slope_difference <= slope_selection_tolerance:
            updated_item = dict(item)
            updated_item["slope_difference"] = slope_difference
            updated_item["selection_mode"] = "slope_compatible_preferred"
            slope_compatible_candidates.append(updated_item)

    if slope_compatible_candidates:
        # Prefer best slope match first, distance second.
        slope_compatible_candidates.sort(
            key=lambda item: (
                item.get("slope_difference", 999),
                item.get("distance_points", 999),
            )
        )
        return slope_compatible_candidates[0]

    fallback = dict(ranked_candidates[0])
    fallback["selection_mode"] = "nearest_fallback_no_slope_compatible_candidate"

    return fallback


def build_match_debug(
    label: dict,
    best_match: dict | None,
    ranked_candidates: list[dict],
    status: str,
    reason: str,
    tolerance: float,
    candidate_line_count: int,
    max_segment_distance_points: float = MAX_SEGMENT_DISTANCE_POINTS,
) -> dict:
    debug = {
        "match_method": "ranked_nearby_point_to_segment_with_slope_preference",
        "label_id": label.get("label_id"),
        "printed_label": label.get("text"),
        "label_center": label.get("center"),
        "target_slope": label.get("target_slope"),
        "tolerance": tolerance,
        "candidate_line_count_total": candidate_line_count,
        "candidate_line_count_within_search_radius": len(ranked_candidates),
        "max_search_distance_points": max_segment_distance_points,
        "decision": status,
        "decision_reason": reason or "Measured slope matched printed label within tolerance.",
        "candidate_ranking": [
            summarize_candidate_line(
                rank=index,
                item=item,
                tolerance=tolerance,
            )
            for index, item in enumerate(
                ranked_candidates[:TOP_CANDIDATE_LIMIT],
                start=1,
            )
        ],
    }

    if best_match is None:
        debug.update(
            {
                "chosen_line_id": None,
                "chosen_line_coordinates": None,
                "distance_to_line_points": None,
                "measured_slope": None,
                "slope_difference": None,
                "selection_reason": "No candidate line was close enough to the printed label.",
            }
        )
        return debug

    line = best_match["line"]
    measured_slope = abs(line["slope_decimal"])
    target_slope = abs(label["target_slope"])
    slope_difference = abs(measured_slope - target_slope)

    if slope_difference <= tolerance:
        selection_reason = (
            "Chosen line ranked first because it was slope-compatible and closest among compatible candidates."
        )
    else:
        selection_reason = (
            "No slope-compatible nearby line was found, so the nearest nearby line was selected and flagged."
        )

    debug.update(
        {
            "chosen_line_id": line.get("line_id"),
            "chosen_line_coordinates": line.get("pdf_coordinates"),
            "distance_to_line_points": best_match.get("distance_points"),
            "measured_slope": measured_slope,
            "slope_difference": slope_difference,
            "selection_reason": selection_reason,
            "chosen_line": {
                "line_id": line.get("line_id"),
                "run_ft": line.get("abs_horizontal_run_ft"),
                "rise_ft": line.get("abs_vertical_rise_ft"),
                "slope_decimal": line.get("slope_decimal"),
                "slope_percent": line.get("slope_percent"),
                "pdf_coordinates": line.get("pdf_coordinates"),
            },
        }
    )

    return debug


def validate_slope_label_occurrences(
    slope_labels: list[dict],
    geometry_report: dict,
    slope_tolerance: float = 0.01,
) -> list[dict]:
    candidate_lines = geometry_report.get("candidate_slope_lines", [])
    checks = []

    for label in slope_labels:
        tolerance = slope_tolerance_for_label(label)
        review_tolerance = slope_review_tolerance_for_label(label)

        ranked_candidates = rank_nearby_line_candidates(
            label=label,
            candidate_lines=candidate_lines,
        )

        best_match = None

        if ranked_candidates:
            target_slope = abs(label["target_slope"])

            # Selection tolerance is intentionally looser than final report tolerance.
            # Purpose: choose the intended line first, then let final tolerance decide
            # PASS/FLAG. This prevents tiny close fragments from beating the correct line.
            slope_selection_tolerance = max(0.0065, target_slope * 0.25)

            slope_compatible_candidates = []

            for item in ranked_candidates:
                line = item.get("line", {})
                measured_slope = line.get("slope_decimal")

                if measured_slope is None:
                    continue

                slope_difference = abs(abs(measured_slope) - target_slope)

                if slope_difference <= slope_selection_tolerance:
                    updated_item = dict(item)
                    updated_item["slope_difference"] = slope_difference
                    updated_item["selection_mode"] = "slope_compatible_preferred"
                    slope_compatible_candidates.append(updated_item)

            if slope_compatible_candidates:
                slope_compatible_candidates.sort(
                    key=lambda item: (
                        item.get("slope_difference", 999),
                        item.get("distance_points", 999),
                    )
                )
                best_match = slope_compatible_candidates[0]
            else:
                best_match = dict(ranked_candidates[0])
                best_match["selection_mode"] = "nearest_fallback_no_slope_compatible_candidate"

        if best_match is None:
            status = "REVIEW"
            reason = (
                "No nearby measured geometry line could be confidently matched "
                "to this printed slope label."
            )

            checks.append(
                {
                    "label_id": label["label_id"],
                    "printed_label": label["text"],
                    "page_number": label["page_number"],
                    "label_center": label["center"],
                    "target_slope": label["target_slope"],
                    "nearest_measured_slope": None,
                    "difference": None,
                    "tolerance": tolerance,
                    "status": status,
                    "reason": reason,
                    "nearest_measured_line": None,
                    "match_debug": build_match_debug(
                        label=label,
                        best_match=None,
                        ranked_candidates=ranked_candidates,
                        status=status,
                        reason=reason,
                        tolerance=tolerance,
                        candidate_line_count=len(candidate_lines),
                    ),
                }
            )
            continue

        line = best_match["line"]
        measured_slope = abs(line["slope_decimal"])
        difference = abs(measured_slope - abs(label["target_slope"]))

        if difference <= tolerance:
            status = "PASS"
            reason = (
                "Measured nearby geometry matches the printed slope label "
                "within practical PDF measurement tolerance."
            )
        elif difference <= review_tolerance:
            status = "REVIEW"
            reason = (
                "Measured nearby geometry is close to the printed slope label "
                "but outside the preferred pass tolerance. Manual review is recommended."
            )
        else:
            status = "FLAG"
            reason = (
                "Measured nearby geometry does not match the printed slope label "
                "within practical PDF measurement tolerance."
            )

        checks.append(
            {
                "label_id": label["label_id"],
                "printed_label": label["text"],
                "page_number": label["page_number"],
                "label_center": label["center"],
                "target_slope": label["target_slope"],
                "nearest_measured_slope": measured_slope,
                "difference": difference,
                "tolerance": tolerance,
                "distance_to_line_points": best_match["distance_points"],
                "status": status,
                "reason": reason,
                "nearest_measured_line": {
                    "line_id": line.get("line_id"),
                    "run_ft": line.get("abs_horizontal_run_ft"),
                    "rise_ft": line.get("abs_vertical_rise_ft"),
                    "slope_decimal": line.get("slope_decimal"),
                    "slope_percent": line.get("slope_percent"),
                    "pdf_coordinates": line.get("pdf_coordinates"),
                },
                "match_debug": build_match_debug(
                    label=label,
                    best_match=best_match,
                    ranked_candidates=ranked_candidates,
                    status=status,
                    reason=reason,
                    tolerance=tolerance,
                    candidate_line_count=len(candidate_lines),
                ),
            }
        )

    return checks
