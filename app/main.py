import argparse
from pathlib import Path

from app.agent_runner import run_full_qc
from app.single_section_runner import run_single_cross_section_qc


def print_generated_files(results: dict):
    print()
    print("Done.")
    print("Generated files:")

    for name, path in results.items():
        print(f"- {name}: {path}")


def main():
    parser = argparse.ArgumentParser(description="Engineering PDF QC tool")

    parser.add_argument(
        "pdf_path",
        nargs="?",
        default="input_pdfs/1st_xs.pdf",
        help="Path to input PDF",
    )

    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory",
    )

    parser.add_argument(
        "--single-cross-section-mode",
        action="store_true",
        help="Analyze PDFs where each page contains one cross section. Processes all pages.",
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if args.single_cross_section_mode:
        output_root = args.output_dir or "runs_single_section"

        result = run_single_cross_section_qc(
            pdf_path=str(pdf_path),
            output_root=output_root,
        )

        print()
        print("Single cross-section mode complete.")
        print(f"Run folder: {result['run_dir']}")
        print(f"Results JSON: {result['artifacts']['results_json']}")
        print(f"Report PDF: {result['artifacts']['report_pdf']}")
        print(f"Marked PDF: {result['artifacts']['marked_pdf']}")
        return

    results = run_full_qc(
        str(pdf_path),
        output_base_dir=args.output_dir or "runs",
    )

    print_generated_files(results)


if __name__ == "__main__":
    main()
