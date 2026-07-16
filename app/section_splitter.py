from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path
from typing import Any

import fitz


STATION_PATTERN = re.compile(r"\b\d{2,5}\+\d{2}(?:\.\d+)?\b")


def safe_stem(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def extract_station_words(page: fitz.Page) -> list[dict[str, Any]]:
    words = page.get_text("words")
    stations = []

    for word in words:
        x0, y0, x1, y1, text, block_no, line_no, word_no = word
        cleaned = text.strip()

        match = STATION_PATTERN.search(cleaned)
        if not match:
            continue

        station = match.group(0)

        stations.append(
            {
                "station": station,
                "bbox": {
                    "x0": float(x0),
                    "y0": float(y0),
                    "x1": float(x1),
                    "y1": float(y1),
                },
                "center": {
                    "x": float((x0 + x1) / 2),
                    "y": float((y0 + y1) / 2),
                },
                "text": cleaned,
            }
        )

    return stations


def dedupe_station_words(
    stations: list[dict[str, Any]],
    y_tolerance: float = 10.0,
) -> list[dict[str, Any]]:
    output = []

    for station in sorted(stations, key=lambda item: (item["station"], item["center"]["y"])):
        duplicate = False

        for existing in output:
            same_station = station["station"] == existing["station"]
            close_y = abs(station["center"]["y"] - existing["center"]["y"]) <= y_tolerance

            if same_station and close_y:
                duplicate = True
                break

        if not duplicate:
            output.append(station)

    return sorted(output, key=lambda item: item["center"]["y"])


def find_horizontal_blank_runs(
    page: fitz.Page,
    zoom: float = 1.0,
    dark_threshold: int = 235,
    max_dark_ratio: float = 0.002,
    min_run_height_points: float = 12.0,
) -> list[dict[str, float]]:
    """
    Render the page and find horizontal rows with almost no ink.

    This is used to locate the white gap between stacked cross-section grids.
    """

    pix = page.get_pixmap(
        matrix=fitz.Matrix(zoom, zoom),
        colorspace=fitz.csRGB,
        alpha=False,
    )

    width = pix.width
    height = pix.height
    samples = pix.samples
    channels = pix.n

    # Ignore extreme page edges; use central drawing area.
    x_start = int(width * 0.04)
    x_end = int(width * 0.96)
    x_step = 4

    blank_rows = []

    for y in range(height):
        dark_count = 0
        sample_count = 0

        row_offset = y * width * channels

        for x in range(x_start, x_end, x_step):
            idx = row_offset + x * channels
            r = samples[idx]
            g = samples[idx + 1]
            b = samples[idx + 2]

            # Grid/text/vector lines are usually darker than white background.
            if r < dark_threshold or g < dark_threshold or b < dark_threshold:
                dark_count += 1

            sample_count += 1

        dark_ratio = dark_count / max(sample_count, 1)

        if dark_ratio <= max_dark_ratio:
            blank_rows.append(y)

    runs = []

    if not blank_rows:
        return runs

    start = blank_rows[0]
    prev = blank_rows[0]

    for row in blank_rows[1:]:
        if row == prev + 1:
            prev = row
            continue

        runs.append((start, prev))
        start = row
        prev = row

    runs.append((start, prev))

    min_run_height_pixels = min_run_height_points * zoom

    output = []

    for start_row, end_row in runs:
        if (end_row - start_row + 1) < min_run_height_pixels:
            continue

        y0 = page.rect.y0 + (start_row / zoom)
        y1 = page.rect.y0 + (end_row / zoom)
        yc = (y0 + y1) / 2

        output.append(
            {
                "y0": y0,
                "y1": y1,
                "center_y": yc,
                "height": y1 - y0,
            }
        )

    return output


def choose_gap_cut_between_stations(
    blank_runs: list[dict[str, float]],
    upper_station: dict[str, Any],
    lower_station: dict[str, Any],
) -> float | None:
    """
    Choose the best white gap between two station labels.

    The station labels are near the bottom of their own cross sections,
    so the ideal gap is between the upper station label and the lower station label.
    """

    upper_y = upper_station["center"]["y"]
    lower_y = lower_station["center"]["y"]

    candidates = [
        run for run in blank_runs
        if upper_y < run["center_y"] < lower_y
    ]

    if not candidates:
        return None

    # Prefer the tallest blank run.
    candidates.sort(key=lambda run: run["height"], reverse=True)
    return candidates[0]["center_y"]


def section_bands_from_station_positions(
    page: fitz.Page,
    stations: list[dict[str, Any]],
    min_band_height: float = 120.0,
) -> list[dict[str, Any]]:
    """
    Build horizontal crop bands for stacked cross sections.

    Strategy:
    - Station labels are usually printed near the bottom-right of each cross section.
    - Therefore, the clean split line is just below each station label.
    - This should land in the white gap between stacked grids.
    """

    page_rect = page.rect

    if len(stations) <= 1:
        return [
            {
                "station": stations[0]["station"] if stations else None,
                "clip": fitz.Rect(page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1),
                "method": "copied_full_page",
            }
        ]

    stations_sorted = sorted(stations, key=lambda item: item["center"]["y"])

    padding_below_station = 10.0
    cuts = []

    for idx, station in enumerate(stations_sorted[:-1]):
        next_station = stations_sorted[idx + 1]

        station_bottom = station["bbox"]["y1"]
        proposed_cut = station_bottom + padding_below_station

        # Safety fallback: the cut must be between this station and the next station.
        if not (station["center"]["y"] < proposed_cut < next_station["center"]["y"]):
            proposed_cut = (station["center"]["y"] + next_station["center"]["y"]) / 2

        cuts.append(proposed_cut)

    boundaries = [page_rect.y0] + cuts + [page_rect.y1]

    bands = []

    for idx, station in enumerate(stations_sorted):
        y0 = boundaries[idx]
        y1 = boundaries[idx + 1]

        if (y1 - y0) < min_band_height:
            continue

        clip = fitz.Rect(page_rect.x0, y0, page_rect.x1, y1)

        bands.append(
            {
                "station": station["station"],
                "clip": clip,
                "method": "station_bottom_gap_split",
            }
        )

    return bands


def split_pdf_pages_by_station_bands(
    input_pdf: str | Path,
    output_pdf: str | Path,
) -> dict[str, Any]:
    input_pdf = Path(input_pdf)
    output_pdf = Path(output_pdf)

    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    src_doc = fitz.open(input_pdf)
    out_doc = fitz.open()

    split_report = {
        "input_pdf": str(input_pdf),
        "output_pdf": str(output_pdf),
        "source_pages": len(src_doc),
        "output_pages": 0,
        "pages": [],
    }

    for page_index, page in enumerate(src_doc):
        page_number = page_index + 1
        stations = dedupe_station_words(extract_station_words(page))

        page_info = {
            "source_page_number": page_number,
            "station_count": len(stations),
            "stations": [item["station"] for item in stations],
            "sections": [],
        }

        bands = section_bands_from_station_positions(page, stations)

        for band in bands:
            clip = band["clip"]
            new_page = out_doc.new_page(width=clip.width, height=clip.height)
            target_rect = fitz.Rect(0, 0, clip.width, clip.height)

            new_page.show_pdf_page(
                target_rect,
                src_doc,
                page_index,
                clip=clip,
            )

            split_report["output_pages"] += 1
            page_info["sections"].append(
                {
                    "output_page_number": split_report["output_pages"],
                    "station": band.get("station"),
                    "method": band.get("method"),
                    "clip": {
                        "x0": clip.x0,
                        "y0": clip.y0,
                        "x1": clip.x1,
                        "y1": clip.y1,
                    },
                }
            )

        split_report["pages"].append(page_info)

    # Safety fallback:
    # If no station bands / sections were detected, do not crash by saving
    # an empty PDF. Use the original PDF as the normalized output and let
    # the downstream analyzer continue in single-page mode.
    if split_report["output_pages"] == 0:
        out_doc.close()
        src_doc.close()

        output_pdf = Path(output_pdf)
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(input_pdf, output_pdf)

        split_report["output_pages"] = split_report["source_pages"]
        split_report["fallback_to_original"] = True
        split_report["fallback_reason"] = (
            "No station-based section bands were detected, so the original PDF "
            "was used as the normalized analyzer input."
        )

        for page_info in split_report["pages"]:
            page_info["sections"].append(
                {
                    "output_page_number": page_info["source_page_number"],
                    "station": None,
                    "method": "fallback_original_page",
                    "clip": None,
                }
            )

        return split_report

    out_doc.save(output_pdf)
    out_doc.close()
    src_doc.close()

    split_report["fallback_to_original"] = False

    return split_report


def default_output_path(input_pdf: str | Path) -> Path:
    input_pdf = Path(input_pdf)
    clean_stem = re.sub(r"_split.*$", "", input_pdf.stem)
    return input_pdf.parent / f"{safe_stem(clean_stem)}_split_sections.pdf"


def main():
    parser = argparse.ArgumentParser(description="Split multi-cross-section PDF pages into one section per page.")
    parser.add_argument("input_pdf", help="Input PDF path")
    parser.add_argument("--output-pdf", default=None, help="Output normalized PDF path")

    args = parser.parse_args()

    input_pdf = Path(args.input_pdf)
    output_pdf = Path(args.output_pdf) if args.output_pdf else default_output_path(input_pdf)

    report = split_pdf_pages_by_station_bands(input_pdf, output_pdf)

    print("Section splitting complete.")
    print(f"Input PDF: {report['input_pdf']}")
    print(f"Output PDF: {report['output_pdf']}")
    print(f"Source pages: {report['source_pages']}")
    print(f"Output pages: {report['output_pages']}")
    print()

    for page in report["pages"]:
        print(f"Source page {page['source_page_number']}:")
        print(f"  Stations detected: {page['stations']}")
        for section in page["sections"]:
            print(
                f"  → Output page {section['output_page_number']} "
                f"station={section.get('station')} "
                f"method={section.get('method')}"
            )


if __name__ == "__main__":
    main()
