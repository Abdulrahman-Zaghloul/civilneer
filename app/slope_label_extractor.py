from pathlib import Path
import re
import fitz


def is_decimal_slope_label(text: str) -> bool:
    try:
        value = float(text)
    except ValueError:
        return False

    # Keep common plan slope labels like 0.02, 0.03, etc.
    return 0.001 <= value <= 0.50 and text.startswith("0.")


def normalize_slope_text(text: str) -> str:
    return text.strip().replace("％", "%").replace(" ", "")


def is_percent_slope_label(text: str) -> bool:
    cleaned = normalize_slope_text(text)

    if not re.match(r"^\d+(?:\.\d+)?%$", cleaned):
        return False

    try:
        value = float(cleaned[:-1])
    except ValueError:
        return False

    # Civil plan percent slopes are commonly small, for example 0.50%, 0.8%, 2.00%.
    # Keep a generous ceiling to avoid weird text being treated as a slope.
    return 0 < value <= 50


def percent_slope_to_decimal(label: str) -> float | None:
    cleaned = normalize_slope_text(label)

    if not is_percent_slope_label(cleaned):
        return None

    return float(cleaned[:-1]) / 100.0


def is_side_slope_label(text: str) -> bool:
    if ":" not in text:
        return False

    parts = text.split(":")
    if len(parts) != 2:
        return False

    try:
        vertical = int(parts[0])
        horizontal = int(parts[1])
    except ValueError:
        return False

    # Civil side slopes only. Reject timestamps like 1:41.
    return 1 <= vertical <= 4 and 1 <= horizontal <= 10


def side_slope_to_decimal(label: str) -> float | None:
    try:
        vertical, horizontal = label.split(":")
        return float(vertical) / float(horizontal)
    except ValueError:
        return None


def label_to_target_slope(label: str) -> float | None:
    cleaned = normalize_slope_text(label)

    if is_percent_slope_label(cleaned):
        return percent_slope_to_decimal(cleaned)

    if is_decimal_slope_label(cleaned):
        return float(cleaned)

    if is_side_slope_label(cleaned):
        return side_slope_to_decimal(cleaned)

    return None


def extract_slope_label_occurrences(pdf_path: str) -> list[dict]:
    """
    Extract every printed slope label occurrence from the PDF using word coordinates.

    This is different from fact_extractor.py, which extracts unique slope values.
    This file keeps duplicates and stores label locations.
    """

    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    labels = []

    label_id = 1

    for page_index, page in enumerate(doc):
        words = page.get_text("words")

        for word in words:
            x0, y0, x1, y1, text, block_no, line_no, word_no = word
            cleaned = text.strip()

            if not cleaned:
                continue

            cleaned = normalize_slope_text(cleaned)

            if not (
                is_decimal_slope_label(cleaned)
                or is_side_slope_label(cleaned)
                or is_percent_slope_label(cleaned)
            ):
                continue

            target_slope = label_to_target_slope(cleaned)

            if target_slope is None:
                continue

            labels.append(
                {
                    "label_id": label_id,
                    "page_number": page_index + 1,
                    "text": cleaned,
                    "target_slope": target_slope,
                    "bbox": {
                        "x0": x0,
                        "y0": y0,
                        "x1": x1,
                        "y1": y1,
                    },
                    "center": {
                        "x": (x0 + x1) / 2,
                        "y": (y0 + y1) / 2,
                    },
                }
            )

            label_id += 1

    doc.close()
    return labels
