from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


POINTS_PER_INCH = 72
RENDER_DPI = 200


def pdf_point_to_pixel(value: float) -> float:
    return value * (RENDER_DPI / POINTS_PER_INCH)


def create_geometry_debug_overlay(
    rendered_image_path: str,
    candidate_lines: list[dict],
    output_path: str,
    max_lines: int = 50,
) -> str:
    """
    Draw measured candidate geometry lines over the rendered PDF page.

    Long candidate lines are drawn first so we can visually verify
    whether the tool is finding real engineering geometry.
    """

    image_path = Path(rendered_image_path)

    if not image_path.exists():
        raise FileNotFoundError(f"Rendered image not found: {rendered_image_path}")

    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    for line in candidate_lines[:max_lines]:
        coords = line["pdf_coordinates"]

        x1 = pdf_point_to_pixel(coords["x1"])
        y1 = pdf_point_to_pixel(coords["y1"])
        x2 = pdf_point_to_pixel(coords["x2"])
        y2 = pdf_point_to_pixel(coords["y2"])

        line_id = line["line_id"]
        slope = line["slope_decimal"]
        run = line["abs_horizontal_run_ft"]

        draw.line((x1, y1, x2, y2), fill="red", width=6)

        label = f"{line_id} | m={slope:.3f} | run={run:.1f}'"
        draw.rectangle((x1, y1 - 22, x1 + 220, y1), fill="white")
        draw.text((x1, y1 - 22), label, fill="red")

    image.save(output_path)
    return output_path
