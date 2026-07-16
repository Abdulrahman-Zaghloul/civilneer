# PDF Engineer Agent

A local web app and command-line tool for reviewing engineering cross-section PDFs.

The app reads civil engineering cross-section drawings, extracts slope labels and geometry, compares the printed design slopes against measured PDF geometry, and generates review artifacts for an engineer to inspect.

## What It Does

- Upload a cross-section PDF through a web interface
- Automatically split stacked cross sections into one section per analysis page
- Extract printed slope labels such as `1:2`, `1:10`, `0.8%`, and `0.50%`
- Measure nearby PDF geometry
- Compare printed slope labels against measured geometry
- Generate a QC report PDF
- Generate a marked PDF with transparent status dots
- Generate JSON results for debugging or future automation

## Outputs

After analysis, the app produces:

- `single_section_report.pdf` — summary report with pass, review, and flag results
- `single_section_marked.pdf` — original drawing marked with transparent status dots
- `single_section_results.json` — structured machine-readable results
- `preprocessing_report.json` — information about PDF splitting/preprocessing

## Status Meanings

| Status | Meaning |
|---|---|
| PASS | The measured geometry confidently matches the printed label within tolerance |
| REVIEW | The app could not confidently verify the item and a human should review it |
| FLAG | The app confidently found a mismatch outside tolerance |
| FAIL | A processing/runtime issue occurred |

Important: uncertain checks should be marked as `REVIEW`, not `FLAG`.

## Run With Docker

Build and start the web app:

```bash
docker compose up --build
```

Open the app:

```text
http://127.0.0.1:8000
```

Stop the app:

```bash
docker compose down
```

## Run From the Command Line

Analyze a PDF directly:

```bash
python -m app.main input_pdfs/your_file.pdf --single-cross-section-mode
```

Open the latest results:

```bash
LATEST_SINGLE=$(ls -td runs_single_section/* | head -1)

xdg-open "$LATEST_SINGLE/reports/single_section_report.pdf"
xdg-open "$LATEST_SINGLE/reports/single_section_marked.pdf"
```

## Auto-Splitting

If a PDF page contains multiple stacked cross sections, the app attempts to create a normalized PDF where each cross section is placed on its own analysis page.

The results page shows whether auto-splitting was used.

Current auto-splitting is designed for stacked cross sections with detectable station labels. Unsupported layouts should be marked for review rather than treated as confirmed failures.

## Marked PDF Legend

The marked PDF uses transparent dots:

- Green dot = PASS
- Orange dot = REVIEW
- Red dot = FLAG/FAIL

Small labels such as `S1`, `S2`, and `S3` connect each marked item to the report table.

## Project Structure

```text
app/
  checks/                  QC check logic
  main.py                  CLI entry point
  web_api.py               FastAPI web app
  section_splitter.py      PDF auto-splitting logic
  single_section_runner.py Single cross-section workflow
  single_section_report_pdf.py
  single_section_marker_pdf.py

templates/                 Web page templates
static/                    CSS styling
web_uploads/               Uploaded PDFs, ignored by Git
web_jobs/                  Web-generated results, ignored by Git
runs_single_section/       CLI-generated results, ignored by Git
```

## Current Limitations

This is a prototype engineering review assistant, not a replacement for licensed engineering judgment.

Known limitations:

- Works best on clean cross-section PDFs
- Auto-splitting currently targets stacked sections with station labels
- Geometry extraction may miss or misclassify some linework
- Crowded drawings may require manual review
- A `REVIEW` result means the app is uncertain, not that the drawing is wrong

## Goal

The goal of this project is to demonstrate a practical engineering PDF QC workflow using Python, PDF processing, geometry extraction, FastAPI, Docker, and structured reporting.
