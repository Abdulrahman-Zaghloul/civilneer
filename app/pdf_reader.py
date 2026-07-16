from pathlib import Path
import fitz


def extract_text_from_pdf(pdf_path: str) -> str:
    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    all_text = []

    for page_number, page in enumerate(doc, start=1):
        text = page.get_text()
        all_text.append(f"\n--- Page {page_number} ---\n{text}")

    doc.close()
    return "\n".join(all_text)


def render_pdf_pages(pdf_path: str, output_folder: str) -> list[str]:
    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = Path(output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    rendered_paths = []

    for page_number, page in enumerate(doc, start=1):
        output_path = output_dir / f"page_{page_number}.png"
        pix = page.get_pixmap(dpi=200)
        pix.save(output_path)
        rendered_paths.append(str(output_path))

    doc.close()
    return rendered_paths
