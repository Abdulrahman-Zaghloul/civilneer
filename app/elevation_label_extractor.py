from pathlib import Path
import re
import fitz


def clean_text(value: str) -> str:
    return value.strip().replace(",", "")


def median(values: list[float]) -> float:
    values = sorted(values)
    n = len(values)

    if n == 0:
        raise ValueError("Cannot calculate median of empty list.")

    mid = n // 2

    if n % 2 == 1:
        return values[mid]

    return (values[mid - 1] + values[mid]) / 2


def linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """
    Fit y = a*x + b.
    Here:
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


def cluster_y_values(candidates: list[dict], tolerance: float = 4.0) -> list[list[dict]]:
    clusters = []

    for candidate in sorted(candidates, key=lambda item: item["center"]["y"]):
        placed = False

        for cluster in clusters:
            cluster_y = median([item["center"]["y"] for item in cluster])

            if abs(candidate["center"]["y"] - cluster_y) <= tolerance:
                cluster.append(candidate)
                placed = True
                break

        if not placed:
            clusters.append([candidate])

    return clusters


def build_elevation_grid_calibration(pdf_path: str) -> dict:
    """
    Compatibility wrapper.

    The real Elevation Resolver v2 lives in app.checks.elevation_checks.
    Keeping this wrapper lets older app code continue calling the same function name.
    """

    from app.checks.elevation_checks import build_elevation_grid_calibration as build_v2_calibration

    return build_v2_calibration(pdf_path)


def extract_elevation_label_occurrences(pdf_path: str) -> list[dict]:
    """
    Extract elevation callouts with approximate PDF locations.

    Examples:
    EL. 43.92
    TOB EL. 13.60
    BTM EL. 9.00
    """

    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    labels = []
    label_id = 1

    pattern = re.compile(
        r"(?:(TOB|BTM)\s+)?EL\.?\s*([0-9]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    )

    for page_index, page in enumerate(doc):
        words = page.get_text("words")

        grouped_lines = {}

        for word in words:
            x0, y0, x1, y1, text, block_no, line_no, word_no = word
            key = (page_index, block_no, line_no)

            grouped_lines.setdefault(key, []).append(
                {
                    "text": text,
                    "bbox": {
                        "x0": x0,
                        "y0": y0,
                        "x1": x1,
                        "y1": y1,
                    },
                    "word_no": word_no,
                }
            )

        for key, line_words in grouped_lines.items():
            line_words = sorted(line_words, key=lambda item: item["bbox"]["x0"])
            line_text = " ".join(item["text"] for item in line_words)

            matches = list(pattern.finditer(line_text))

            if not matches:
                continue

            line_x0 = min(item["bbox"]["x0"] for item in line_words)
            line_y0 = min(item["bbox"]["y0"] for item in line_words)
            line_x1 = max(item["bbox"]["x1"] for item in line_words)
            line_y1 = max(item["bbox"]["y1"] for item in line_words)

            for match in matches:
                label_type = match.group(1).upper() if match.group(1) else "EL"
                elevation_value = float(match.group(2))
                elevation_text = match.group(2)

                value_word = None

                for item in line_words:
                    cleaned_word = clean_text(item["text"])
                    if cleaned_word == elevation_text:
                        value_word = item
                        break

                if value_word:
                    bbox = value_word["bbox"]
                else:
                    bbox = {
                        "x0": line_x0,
                        "y0": line_y0,
                        "x1": line_x1,
                        "y1": line_y1,
                    }

                labels.append(
                    {
                        "label_id": label_id,
                        "page_number": page_index + 1,
                        "label_type": label_type,
                        "text": f"{label_type} EL. {elevation_text}" if label_type in ["TOB", "BTM"] else f"EL. {elevation_text}",
                        "elevation": elevation_value,
                        "bbox": bbox,
                        "line_text": line_text,
                        "center": {
                            "x": (bbox["x0"] + bbox["x1"]) / 2,
                            "y": (bbox["y0"] + bbox["y1"]) / 2,
                        },
                    }
                )

                label_id += 1

    doc.close()
    return labels
