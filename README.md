# Civilneer

Civilneer is a web-based PDF review assistant for civil engineering cross-section sheets. It analyzes uploaded cross-section PDFs, extracts slope and elevation labels, compares them against measured PDF geometry, and generates a marked PDF along with a text-based engineering review report.

> **Disclaimer:** Civilneer is an engineering review aid. It does **not** replace review by a licensed Professional Engineer.

---

## Features

- Upload civil engineering cross-section PDFs
- Detect printed slope labels such as `2.00%`, `1:4`, and `1:2`
- Measure nearby PDF geometry and compare it against printed values
- Detect elevation labels such as `EL. 45.50`
- Calibrate profile grid elevations where possible
- Generate:
  - Marked PDF
  - Text-based report PDF
  - Downloadable review package

---

## Current Scope

Civilneer currently focuses on **cross-section review workflows**.

Supported review areas include:

- Slope label validation
- Elevation label validation
- Marked drawing generation
- Compact engineering report generation
- Local Docker-based web application workflow

---

## Tech Stack

- Python
- FastAPI
- Jinja2
- PyMuPDF
- pdfminer.six
- Docker
- HTML/CSS

---

## Project Structure

```text
app/                 Core PDF analysis and web application logic
app/checks/          Slope and elevation validation checks
templates/           Jinja2 HTML templates
static/              CSS and front-end assets
Dockerfile           Container build
docker-compose.yml   Local Docker workflow
```

---

## Running Locally

Clone the repository:

```bash
git clone git@github.com:Abdulrahman-Zaghloul/civilneer-public.git
cd civilneer-public
```

Optional: create a local environment file if you want to customize runtime settings:

```bash
cp .env.example .env
```

Start the application:

```bash
docker compose up --build
```

Open your browser:

```text
http://127.0.0.1:8000
```

The Cross-Section Analyzer is available at:

```text
http://127.0.0.1:8000/cross-section-analyzer
```

---

## Output Files

For each uploaded PDF, Civilneer generates:

- A marked PDF showing engineering review markers
- A report PDF summarizing measurements, checks, and review statuses
- A downloadable package containing the generated review outputs

---

## Review Statuses

Civilneer uses conservative engineering review statuses:

| Status | Meaning |
|--------|---------|
| **PASS** | Measured evidence is within tolerance. |
| **REVIEW** | The result is uncertain or close to the tolerance and should be checked manually. |
| **FLAG** | Measured evidence appears inconsistent with the printed label. |

---

## Limitations

Civilneer works from **PDF-extracted geometry**, not the original CAD model.

Results may be affected by:

- PDF export quality
- Fragmented vector geometry
- Missing or ambiguous grid labels
- Overlapping annotations
- Scanned or rasterized drawings
- Non-standard drawing formats

When sufficient confidence cannot be established, Civilneer returns **REVIEW** rather than claiming engineering certainty.

---

## Roadmap

Planned improvements include:

- Improved geometry feature recognition
- Interactive visual candidate review
- AI-assisted explanations for uncertain findings
- User accounts and project history
- Production deployment workflow

---

## License

This project is shared as a portfolio project.

Please add an appropriate open-source or commercial license before reuse or distribution.

