from pathlib import Path
from PIL import Image, ImageDraw


POINTS_PER_INCH = 72
RENDER_DPI = 200


def pdf_point_to_pixel(value: float) -> float:
    return value * (RENDER_DPI / POINTS_PER_INCH)


def draw_pdf_line(draw: ImageDraw.ImageDraw, line: dict, color: str, width: int = 4):
    x1 = pdf_point_to_pixel(line["x1"])
    y1 = pdf_point_to_pixel(line["y1"])
    x2 = pdf_point_to_pixel(line["x2"])
    y2 = pdf_point_to_pixel(line["y2"])

    draw.line((x1, y1, x2, y2), fill=color, width=width)


def create_elevation_label_overlay(
    rendered_image_path: str,
    elevation_validation: list[dict],
    output_path: str,
) -> str:
    image_path = Path(rendered_image_path)

    if not image_path.exists():
        raise FileNotFoundError(f"Rendered image not found: {rendered_image_path}")

    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    for check in elevation_validation:
        label_id = check["label_id"]
        status = check["status"]
        target_elevation = check["target_elevation"]
        measured_elevation = check.get("measured_elevation")
        method = check.get("method")
        label_center = check["label_center"]
        leader_line = check.get("leader_line")
        intersection = check.get("intersection")
        target_line = check.get("target_line")

        if status == "PASS":
            color = "green"
        elif status == "FLAG":
            color = "orange"
        else:
            color = "red"

        # Draw detected leader line for vertical EL callouts.
        if leader_line:
            draw_pdf_line(draw, leader_line, "blue", width=4)

        # Draw matched target geometry line.
        if target_line:
            draw_pdf_line(draw, target_line, "red", width=5)

        # Draw only the actual measured/intersection point.
        # This removes the old green text-position marker.
        if intersection:
            ix = pdf_point_to_pixel(intersection["x"])
            iy = pdf_point_to_pixel(intersection["y"])

            draw.ellipse(
                (ix - 8, iy - 8, ix + 8, iy + 8),
                fill="purple",
                outline="white",
                width=2,
            )

            label_text = f"EL#{label_id} {target_elevation}"
            if measured_elevation is not None:
                label_text += f" -> {measured_elevation:.2f}"

            draw.text((ix + 10, iy - 8), label_text, fill="purple")
            continue

        # Only show fallback markers when no real measured point exists.
        label_x = pdf_point_to_pixel(label_center["x"])
        label_y = pdf_point_to_pixel(label_center["y"])

        draw.ellipse(
            (label_x - 8, label_y - 8, label_x + 8, label_y + 8),
            fill=color,
            outline="white",
            width=2,
        )

        fallback_text = f"EL#{label_id} fallback"
        if method == "label_position_fallback":
            fallback_text += " - review"

        draw.text((label_x + 10, label_y - 8), fallback_text, fill=color)

    image.save(output_path)
    return output_path
