from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import fitz


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SEARCH_ROOTS = [
    PROJECT_ROOT / "tests" / "regression_outputs",
    PROJECT_ROOT / "web_jobs",
    PROJECT_ROOT / "runs_single_section",
]

STATUS_FILTER_DEFAULT = {"FLAG", "REVIEW"}

RANK_COLORS = {
    1: (0.90, 0.05, 0.05),   # red
    2: (0.05, 0.45, 0.95),   # blue
    3: (0.55, 0.10, 0.80),   # purple
    4: (0.95, 0.55, 0.05),   # orange
    5: (0.00, 0.55, 0.20),   # green
}

STATUS_COLORS = {
    "PASS": (0.00, 0.55, 0.20),
    "REVIEW": (0.95, 0.55, 0.05),
    "FLAG": (0.90, 0.05, 0.05),
    "FAIL": (0.90, 0.05, 0.05),
}


def find_latest_results_json() -> Path | None:
    candidates: list[Path] = []

    for root in DEFAULT_SEARCH_ROOTS:
        if root.exists():
            candidates.extend(root.rglob("single_section_results.json"))

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_results(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Results JSON not found: {path}")

    return json.loads(path.read_text())


def resolve_path(path_value: str | None, base_dir: Path) -> Path | None:
    if not path_value:
        return None

    path = Path(path_value)

    if path.is_absolute():
        return path

    candidate = (PROJECT_ROOT / path).resolve()

    if candidate.exists():
        return candidate

    candidate = (base_dir / path).resolve()

    if candidate.exists():
        return candidate

    return path.resolve()


def fmt(value: Any, digits: int = 4) -> str:
    if value is None or value == "":
        return "—"

    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def draw_text_box(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    color: tuple[float, float, float] = (0, 0, 0),
    fill: tuple[float, float, float] = (1, 1, 1),
    font_size: float = 6.5,
):
    page.draw_rect(
        rect,
        color=color,
        fill=fill,
        width=0.5,
        overlay=True,
        fill_opacity=0.78,
    )

    page.insert_textbox(
        rect + (3, 2, -3, -2),
        text,
        fontsize=font_size,
        fontname="helv",
        color=color,
        overlay=True,
    )


def draw_header(page: fitz.Page, page_number: Any):
    rect = fitz.Rect(18, 14, min(page.rect.width - 18, 560), 52)

    text = (
        f"Slope Candidate Debug Overlay | Page {page_number}\n"
        "Shows top candidate geometry lines for FLAG/REVIEW slope checks. "
        "C1=chosen/top ranked candidate."
    )

    draw_text_box(
        page=page,
        rect=rect,
        text=text,
        color=(0.05, 0.05, 0.05),
        fill=(1, 1, 1),
        font_size=7,
    )


def draw_legend(page: fitz.Page):
    width = 230
    height = 88

    rect = fitz.Rect(
        page.rect.width - width - 18,
        14,
        page.rect.width - 18,
        14 + height,
    )

    legend = (
        "Candidate Line Legend\n"
        "C1 red = top/chosen candidate\n"
        "C2 blue | C3 purple | C4 orange | C5 green\n"
        "Large label marks printed slope text location\n"
        "Use this only for debugging matching logic"
    )

    draw_text_box(
        page=page,
        rect=rect,
        text=legend,
        color=(0.05, 0.05, 0.05),
        fill=(1, 1, 1),
        font_size=6.5,
    )


def draw_label_marker(
    page: fitz.Page,
    label_center: dict[str, Any],
    marker: str,
    status: str,
):
    if not isinstance(label_center, dict):
        return

    if "x" not in label_center or "y" not in label_center:
        return

    point = fitz.Point(float(label_center["x"]), float(label_center["y"]))
    color = STATUS_COLORS.get(status.upper(), (0.1, 0.1, 0.1))

    page.draw_circle(
        point,
        5.0,
        color=color,
        fill=color,
        width=1.0,
        overlay=True,
        fill_opacity=0.28,
        stroke_opacity=0.95,
    )

    label_rect = fitz.Rect(point.x + 6, point.y + 4, point.x + 54, point.y + 20)

    draw_text_box(
        page=page,
        rect=label_rect,
        text=f"{marker} {status}",
        color=color,
        fill=(1, 1, 1),
        font_size=7,
    )


def draw_candidate_line(
    page: fitz.Page,
    candidate: dict[str, Any],
    marker: str,
):
    coords = candidate.get("pdf_coordinates")

    if not isinstance(coords, dict):
        return

    required = ["x1", "y1", "x2", "y2"]

    if not all(key in coords for key in required):
        return

    rank = int(candidate.get("rank", 0))
    color = RANK_COLORS.get(rank, (0, 0, 0))

    p1 = fitz.Point(float(coords["x1"]), float(coords["y1"]))
    p2 = fitz.Point(float(coords["x2"]), float(coords["y2"]))

    page.draw_line(
        p1,
        p2,
        color=color,
        width=2.0 if rank == 1 else 1.35,
        overlay=True,
        stroke_opacity=0.85,
    )

    page.draw_circle(
        p1,
        1.8,
        color=color,
        fill=color,
        width=0.4,
        overlay=True,
        fill_opacity=0.65,
    )

    page.draw_circle(
        p2,
        1.8,
        color=color,
        fill=color,
        width=0.4,
        overlay=True,
        fill_opacity=0.65,
    )

    mid = fitz.Point((p1.x + p2.x) / 2, (p1.y + p2.y) / 2)

    label = (
        f"{marker}-C{rank} "
        f"m={fmt(candidate.get('measured_slope'))} "
        f"d={fmt(candidate.get('slope_difference'))}"
    )

    rect = fitz.Rect(mid.x + 4, mid.y - 10, mid.x + 86, mid.y + 10)

    draw_text_box(
        page=page,
        rect=rect,
        text=label,
        color=color,
        fill=(1, 1, 1),
        font_size=5.8,
    )


def draw_page_overlay(
    page: fitz.Page,
    page_result: dict[str, Any],
    statuses: set[str],
    top_n: int,
):
    draw_header(page, page_result.get("page_number", "—"))
    draw_legend(page)

    slope_checks = page_result.get("slope_checks", [])

    for index, check in enumerate(slope_checks, start=1):
        status = str(check.get("status", "REVIEW")).upper()

        if status not in statuses:
            continue

        marker = f"S{index}"
        debug = check.get("match_debug") or {}
        candidate_ranking = debug.get("candidate_ranking") or []

        draw_label_marker(
            page=page,
            label_center=check.get("label_center") or debug.get("label_center"),
            marker=marker,
            status=status,
        )

        for candidate in candidate_ranking[:top_n]:
            draw_candidate_line(
                page=page,
                candidate=candidate,
                marker=marker,
            )


def create_overlay_pdf(
    results_path: Path,
    output_path: Path | None,
    statuses: set[str],
    top_n: int,
) -> Path:
    results = load_results(results_path)
    base_dir = results_path.parent

    if output_path is None:
        output_path = base_dir / "slope_candidate_debug_overlay.pdf"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    out_doc = fitz.open()

    for page_result in results.get("pages", []):
        input_page_pdf = resolve_path(
            page_result.get("input_page_pdf"),
            base_dir=base_dir,
        )

        if input_page_pdf is None or not input_page_pdf.exists():
            page = out_doc.new_page()
            page.insert_text(
                fitz.Point(72, 72),
                f"Input page PDF not found for page {page_result.get('page_number', '—')}",
                fontsize=12,
            )
            continue

        src_doc = fitz.open(input_page_pdf)
        out_doc.insert_pdf(src_doc, from_page=0, to_page=0)
        src_doc.close()

        page = out_doc[-1]

        draw_page_overlay(
            page=page,
            page_result=page_result,
            statuses=statuses,
            top_n=top_n,
        )

    out_doc.save(output_path)
    out_doc.close()

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a PDF overlay showing top candidate lines for flagged/review slope matches."
    )

    parser.add_argument(
        "--results",
        type=Path,
        help="Path to reports/single_section_results.json. Defaults to latest result.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Output PDF path. Defaults to reports/slope_candidate_debug_overlay.pdf.",
    )

    parser.add_argument(
        "--status",
        nargs="+",
        default=["FLAG", "REVIEW"],
        help="Statuses to include. Default: FLAG REVIEW.",
    )

    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="Number of candidate lines to draw per finding.",
    )

    args = parser.parse_args()

    results_path = args.results or find_latest_results_json()

    if results_path is None:
        print("No single_section_results.json files found.")
        return 1

    results_path = results_path.resolve()
    statuses = {status.upper() for status in args.status}

    output_path = create_overlay_pdf(
        results_path=results_path,
        output_path=args.output,
        statuses=statuses,
        top_n=args.top_n,
    )

    print(f"Results: {results_path}")
    print(f"Overlay: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
