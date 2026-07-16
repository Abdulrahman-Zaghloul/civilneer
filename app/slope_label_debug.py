from pathlib import Path
from PIL import Image, ImageDraw


POINTS_PER_INCH = 72
RENDER_DPI = 200


def pdf_point_to_pixel(value: float) -> float:
    return value * (RENDER_DPI / POINTS_PER_INCH)


def get_line_lookup(geometry_report: dict) -> dict:
    return {
        line["line_id"]: line
        for line in geometry_report.get("candidate_slope_lines", [])
    }


def create_slope_label_match_overlay(
    rendered_image_path: str,
    slope_validation: list[dict],
    geometry_report: dict,
    output_path: str,
) -> str:
    image_path = Path(rendered_image_path)

    if not image_path.exists():
        raise FileNotFoundError(f"Rendered image not found: {rendered_image_path}")

    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    line_lookup = get_line_lookup(geometry_report)

    for check in slope_validation:
        label_id = check["label_id"]
        label_center = check["label_center"]
        nearest_line = check.get("nearest_measured_line")

        label_x = pdf_point_to_pixel(label_center["x"])
        label_y = pdf_point_to_pixel(label_center["y"])

        # Draw compact numbered marker
        radius = 10
        draw.ellipse(
            (label_x - radius, label_y - radius, label_x + radius, label_y + radius),
            fill="blue",
            outline="white",
            width=2,
        )
        draw.text((label_x - 5, label_y - 7), str(label_id), fill="white")

        if not nearest_line:
            continue

        line_id = nearest_line["line_id"]
        full_line = line_lookup.get(line_id)

        if not full_line:
            continue

        coords = full_line["pdf_coordinates"]

        x1 = pdf_point_to_pixel(coords["x1"])
        y1 = pdf_point_to_pixel(coords["y1"])
        x2 = pdf_point_to_pixel(coords["x2"])
        y2 = pdf_point_to_pixel(coords["y2"])

        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2

        # Draw measured line
        draw.line((x1, y1, x2, y2), fill="red", width=5)

        # Draw connector from label marker to matched line
        draw.line((label_x, label_y, mid_x, mid_y), fill="blue", width=2)

    image.save(output_path)
    return output_path
