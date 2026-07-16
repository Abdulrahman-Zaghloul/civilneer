from __future__ import annotations

import json
import os
import secrets
import re
import shutil
import time
import uuid
import zipfile

import fitz
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, HTMLResponse
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.single_section_runner import run_single_cross_section_qc
from app.section_splitter import split_pdf_pages_by_station_bands


app = FastAPI(
    title="CivCheck",
    docs_url=None if os.getenv("CIVCHECK_DISABLE_DOCS", "0") == "1" else "/docs",
    redoc_url=None if os.getenv("CIVCHECK_DISABLE_DOCS", "0") == "1" else "/redoc",
)

# Zero-retention prototype mode:
# Files are stored only in an OS temporary directory and are automatically purged.
EPHEMERAL_ROOT = Path(os.getenv("CIVCHECK_EPHEMERAL_ROOT", "/tmp/civcheck_ephemeral"))
UPLOAD_DIR = EPHEMERAL_ROOT / "uploads"
WEB_RUNS_DIR = EPHEMERAL_ROOT / "jobs"
FEEDBACK_DIR = Path(os.getenv("CIVCHECK_FEEDBACK_DIR", "feedback"))

# Default: keep temporary files for 30 minutes so the browser can preview/download.
# In production, this can be much shorter or replaced by a streaming ZIP download.
RUN_TTL_SECONDS = int(os.getenv("CIVCHECK_RUN_TTL_SECONDS", "1800"))

# Private beta gate.
# If these environment variables are not set, auth is disabled for local development.
BETA_USERNAME = os.getenv("CIVCHECK_BETA_USERNAME", "")
BETA_PASSWORD = os.getenv("CIVCHECK_BETA_PASSWORD", "")

MAX_UPLOAD_BYTES = int(os.getenv("CIVCHECK_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_UPLOAD_PAGES = int(os.getenv("CIVCHECK_MAX_UPLOAD_PAGES", "25"))

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.middleware("http")
async def private_beta_gate(request: Request, call_next):
    """
    Simple private-beta access gate.

    Local dev:
    - If CIVCHECK_BETA_USERNAME/PASSWORD are not set, access is open.

    Private beta:
    - Set CIVCHECK_BETA_USERNAME and CIVCHECK_BETA_PASSWORD.
    - Browser will ask for username/password.
    """
    if not BETA_USERNAME or not BETA_PASSWORD:
        return await call_next(request)

    # Allow static files after auth browser has already loaded page assets.
    # Keep this protected too; no public app assets needed in private beta.
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Basic "):
        return Response(
            "Private beta access required.",
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
        )

    import base64

    try:
        encoded = auth_header.split(" ", 1)[1]
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return Response(
            "Invalid beta access credentials.",
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
        )

    valid_username = secrets.compare_digest(username, BETA_USERNAME)
    valid_password = secrets.compare_digest(password, BETA_PASSWORD)

    if not (valid_username and valid_password):
        return Response(
            "Invalid beta access credentials.",
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
        )

    return await call_next(request)



def no_store_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def ensure_ephemeral_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    WEB_RUNS_DIR.mkdir(parents=True, exist_ok=True)


def purge_expired_temp_files() -> None:
    """
    Delete old uploaded files and analysis job folders.

    This keeps the current prototype privacy-first:
    - no long-term uploaded PDFs
    - no long-term marked PDFs
    - no long-term reports
    - no long-term JSON result files
    """
    ensure_ephemeral_dirs()

    now = time.time()
    cutoff = now - RUN_TTL_SECONDS

    for path in UPLOAD_DIR.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except FileNotFoundError:
            pass

    for run_dir in WEB_RUNS_DIR.iterdir():
        try:
            if run_dir.is_dir() and run_dir.stat().st_mtime < cutoff:
                shutil.rmtree(run_dir, ignore_errors=True)
        except FileNotFoundError:
            pass


def safe_run_name(name: str) -> str:
    if not re.match(r"^[A-Za-z0-9._-]+$", name):
        raise HTTPException(status_code=400, detail="Invalid run name")
    return name


def load_result(run_name: str) -> dict:
    purge_expired_temp_files()

    run_name = safe_run_name(run_name)
    result_path = WEB_RUNS_DIR / run_name / "reports" / "single_section_results.json"

    if not result_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Result not found. This temporary analysis may have expired.",
        )

    return json.loads(result_path.read_text(encoding="utf-8"))


def get_artifact_path(result: dict, artifact_key: str) -> Path:
    artifacts = result.get("artifacts", {})

    if artifact_key not in artifacts:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path = Path(artifacts[artifact_key])

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Artifact file does not exist. This temporary analysis may have expired.",
        )

    return path



def validate_pdf_upload(saved_path: Path) -> None:
    """
    Basic private-beta upload validation.

    This is not a complete security scanner, but it prevents obvious invalid uploads:
    - empty files
    - oversized files
    - files that do not start like PDFs
    """
    file_size = saved_path.stat().st_size

    if file_size <= 0:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    if file_size > MAX_UPLOAD_BYTES:
        saved_path.unlink(missing_ok=True)
        max_mb = MAX_UPLOAD_BYTES / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"PDF is too large. Private beta limit is {max_mb:.0f} MB.",
        )

    with saved_path.open("rb") as f:
        header = f.read(5)

    if header != b"%PDF-":
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")

    try:
        with fitz.open(saved_path) as doc:
            if doc.needs_pass:
                saved_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=400,
                    detail="Password-protected PDFs are not supported in the private beta.",
                )

            page_count = doc.page_count

            if page_count <= 0:
                saved_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="The PDF has no pages.")

            if page_count > MAX_UPLOAD_PAGES:
                saved_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"PDF has too many pages. Private beta limit is {MAX_UPLOAD_PAGES} pages.",
                )

    except HTTPException:
        raise
    except Exception:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="The uploaded PDF could not be opened or appears to be corrupt.",
        )


def prepare_pdf_for_qc(saved_path: Path) -> tuple[Path, dict]:
    """
    Normalize uploaded PDFs before QC.

    If a page contains multiple cross sections, split it into one cross section per page.
    If no split is needed, keep the temporary uploaded PDF.

    Privacy note:
    The preprocessing metadata uses temporary paths only. It does not store the user's
    original uploaded filename.
    """
    normalized_path = saved_path.with_name(f"{saved_path.stem}_normalized.pdf")

    split_report = split_pdf_pages_by_station_bands(
        input_pdf=saved_path,
        output_pdf=normalized_path,
    )

    was_split = any(
        page.get("station_count", 0) > 1
        for page in split_report.get("pages", [])
    ) or split_report.get("output_pages") != split_report.get("source_pages")

    analysis_pdf = normalized_path if was_split else saved_path

    preprocessing = {
        "was_split": was_split,
        "original_pdf": str(saved_path),
        "analysis_pdf": str(analysis_pdf),
        "source_pages": split_report.get("source_pages", 0),
        "analysis_pages": split_report.get("output_pages", 0)
        if was_split
        else split_report.get("source_pages", 0),
        "split_report": split_report,
        "retention_mode": "zero_retention_temp",
        "ttl_seconds": RUN_TTL_SECONDS,
    }

    return analysis_pdf, preprocessing


def _first_value(data: dict, keys: list[str], default: str = "—"):
    for key in keys:
        value = data.get(key)

        if value is None or value == "":
            continue

        return value

    return default


def _format_number(value, digits: int = 4) -> str:
    if value is None or value == "—":
        return "—"

    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _to_float_or_none(value):
    if value is None or value == "—":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _difference_or_none(target, measured):
    target_value = _to_float_or_none(target)
    measured_value = _to_float_or_none(measured)

    if target_value is None or measured_value is None:
        return None

    return abs(target_value - measured_value)


def display_reason(check: dict) -> str:
    """
    Keep the findings table clean.

    PASS rows do not need repeated explanation text.
    REVIEW / FLAG / FAIL rows should keep the reason because those need attention.
    """
    status = str(check.get("status", "REVIEW")).upper()

    if status == "PASS":
        return ""

    return check.get("reason") or ""


def build_finding_rows(result: dict) -> list[dict]:
    rows = []

    for page in result.get("pages", []):
        page_number = page.get("page_number", "—")

        for index, check in enumerate(page.get("slope_checks", []), start=1):
            nearest_line = check.get("nearest_measured_line") or {}

            measured = _first_value(
                check,
                [
                    "nearest_measured_slope",
                    "measured_slope",
                    "measured_slope_decimal",
                ],
                default=None,
            )

            if measured is None:
                measured = nearest_line.get("slope_decimal")

            rows.append(
                {
                    "page": page_number,
                    "marker": f"S{index}",
                    "type": "Slope",
                    "status": check.get("status", "REVIEW"),
                    "printed": _first_value(
                        check,
                        [
                            "printed_label",
                            "label",
                            "label_text",
                            "slope_label",
                        ],
                    ),
                    "target": _format_number(
                        _first_value(
                            check,
                            [
                                "target_slope",
                                "target_slope_decimal",
                                "expected_slope",
                            ],
                            default=None,
                        )
                    ),
                    "measured": _format_number(measured),
                    "difference": _format_number(
                        _first_value(
                            check,
                            [
                                "difference",
                                "slope_difference",
                                "absolute_difference",
                            ],
                            default=None,
                        )
                    ),
                    "reason": display_reason(check),
                }
            )

        for index, check in enumerate(page.get("elevation_checks", []), start=1):
            target_elevation = _first_value(
                check,
                [
                    "target_elevation",
                    "expected_elevation",
                ],
                default=None,
            )

            measured_elevation = _first_value(
                check,
                [
                    "measured_elevation",
                    "actual_elevation",
                ],
                default=None,
            )

            existing_difference = _first_value(
                check,
                [
                    "difference",
                    "elevation_difference",
                    "absolute_difference",
                ],
                default=None,
            )

            calculated_difference = (
                existing_difference
                if existing_difference is not None
                else _difference_or_none(target_elevation, measured_elevation)
            )

            rows.append(
                {
                    "page": page_number,
                    "marker": f"E{index}",
                    "type": "Elevation",
                    "status": check.get("status", "REVIEW"),
                    "printed": _first_value(
                        check,
                        [
                            "printed_label",
                            "label",
                            "label_text",
                            "elevation_label",
                        ],
                    ),
                    "target": _format_number(target_elevation),
                    "measured": _format_number(measured_elevation),
                    "difference": _format_number(calculated_difference),
                    "reason": display_reason(check),
                }
            )

    return rows



STATION_LABEL_PATTERN = re.compile(
    r"\bSTA\.?\s*[:#]?\s*([0-9]{1,5}\+[0-9]{1,3}(?:\.[0-9]+)?)",
    re.IGNORECASE,
)

LOOSE_STATION_PATTERN = re.compile(
    r"\b([0-9]{1,5}\+[0-9]{1,3}(?:\.[0-9]+)?)\b"
)


def _walk_text_values(value):
    """
    Recursively collect text values from result/preprocessing structures.
    This lets the UI find station labels without depending on one exact JSON shape.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_text_values(item)


def _station_from_text(text_value: str) -> str | None:
    match = STATION_LABEL_PATTERN.search(text_value)

    if match:
        return f"STA. {match.group(1)}"

    loose_match = LOOSE_STATION_PATTERN.search(text_value)

    if loose_match and "STA" in text_value.upper():
        return f"STA. {loose_match.group(1)}"

    return None


def build_station_titles(result: dict) -> dict[int, str]:
    """
    Build analysis-page titles from detected station labels.

    Example:
    {
        1: "STA. 170+50.00",
        2: "STA. 170+00.00"
    }
    """
    stations = []

    for text_value in _walk_text_values(result):
        station = _station_from_text(text_value)

        if station and station not in stations:
            stations.append(station)

    return {
        index + 1: station
        for index, station in enumerate(stations)
    }


def build_finding_page_groups(result: dict) -> list[dict]:
    rows = build_finding_rows(result)
    station_titles = build_station_titles(result)

    groups = {}

    for row in rows:
        page = row.get("page", "—")
        groups.setdefault(page, []).append(row)

    grouped_rows = []

    for page, page_rows in groups.items():
        try:
            page_number = int(page)
        except (TypeError, ValueError):
            page_number = None

        title = (
            station_titles.get(page_number)
            if page_number is not None
            else None
        )

        grouped_rows.append(
            {
                "page": page,
                "title": title or f"Analysis Page {page}",
                "rows": page_rows,
                "count": len(page_rows),
            }
        )

    return grouped_rows

def result_context(request: Request, result: dict) -> dict:
    run_dir = Path(result["run_dir"])
    summary = result.get("summary", {})

    return {
        "request": request,
        "result": result,
        "run_name": run_dir.name,
        "total_pages": result.get("total_pages", 0),
        "page_statuses": summary.get("page_statuses", {}),
        "slope_summary": summary.get("slope_checks", {}),
        "elevation_summary": summary.get("elevation_checks", {}),
        "preprocessing": result.get("preprocessing", {}),
        "finding_rows": build_finding_rows(result),
        "finding_page_groups": build_finding_page_groups(result),
        "zero_retention_mode": True,
        "ttl_minutes": max(1, RUN_TTL_SECONDS // 60),
    }




@app.exception_handler(HTTPException)
async def friendly_http_exception_handler(request: Request, exc: HTTPException):
    """
    Show clean browser-facing error pages instead of raw JSON for private beta users.
    API routes can still return simple error behavior later if needed.
    """
    status_code = exc.status_code
    detail = str(exc.detail)

    if status_code == 404:
        title = "Analysis unavailable"
    elif status_code == 410:
        title = "This feature is unavailable"
    elif status_code == 413:
        title = "PDF is too large"
    elif status_code == 400:
        title = "Upload issue"
    elif status_code == 401:
        title = "Private beta access required"
    else:
        title = "Something went wrong"

    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "request": request,
            "title": title,
            "message": detail,
            "status_code": status_code,
        },
        status_code=status_code,
    )



@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(request, "home.html")

@app.get("/cross-section-analyzer")
def home(request: Request):
    purge_expired_temp_files()

    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "request": request,
            "zero_retention_mode": True,
            "ttl_minutes": max(1, RUN_TTL_SECONDS // 60),
            "max_upload_mb": round(MAX_UPLOAD_BYTES / (1024 * 1024)),
            "max_upload_pages": MAX_UPLOAD_PAGES,
        },
    )


@app.post("/analyze")
async def analyze(request: Request, pdf: UploadFile = File(...)):
    purge_expired_temp_files()

    if not pdf.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    ensure_ephemeral_dirs()

    # Do not store the user's original uploaded filename.
    # Use a random UUID-based temporary filename only.
    saved_path = UPLOAD_DIR / f"{uuid.uuid4().hex}.pdf"

    with saved_path.open("wb") as output:
        shutil.copyfileobj(pdf.file, output)

    validate_pdf_upload(saved_path)

    analysis_pdf, preprocessing = prepare_pdf_for_qc(saved_path)

    result = run_single_cross_section_qc(
        pdf_path=analysis_pdf,
        output_root=WEB_RUNS_DIR,
    )

    result["preprocessing"] = preprocessing

    reports_dir = Path(result["run_dir"]) / "reports"
    preprocessing_report_path = reports_dir / "preprocessing_report.json"
    preprocessing_report_path.write_text(
        json.dumps(preprocessing, indent=4),
        encoding="utf-8",
    )

    result.setdefault("artifacts", {})
    result["artifacts"]["preprocessing_json"] = str(preprocessing_report_path)

    result_path = reports_dir / "single_section_results.json"
    result_path.write_text(
        json.dumps(result, indent=4),
        encoding="utf-8",
    )

    run_name = Path(result["run_dir"]).name

    return RedirectResponse(
        url=f"/results/{run_name}",
        status_code=303,
    )


@app.get("/api/results/{run_name}")
def api_result(run_name: str):
    raise HTTPException(status_code=404, detail="Raw JSON results are not available to users.")



def block_public_json_artifact(artifact_key: str) -> None:
    """
    Raw JSON/debug artifacts are internal only.
    Users should receive only the polished PDF outputs.
    """
    if artifact_key in {"results_json", "preprocessing_json"}:
        raise HTTPException(
            status_code=404,
            detail="Raw JSON artifacts are not available to users.",
        )

def resolve_run_artifact(run_name: str, artifact_key: str) -> Path:
    """
    Resolve an artifact path from the temporary results JSON.

    This is used by both preview/download routes.
    """
    purge_expired_temp_files()
    block_public_json_artifact(artifact_key)

    run_name = safe_run_name(run_name)
    run_dir = (WEB_RUNS_DIR / run_name).resolve()
    results_path = run_dir / "reports" / "single_section_results.json"

    if not results_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Run results not found. This temporary analysis may have expired.",
        )

    with results_path.open("r", encoding="utf-8") as f:
        result = json.load(f)

    artifact_path = result.get("artifacts", {}).get(artifact_key)

    if not artifact_path:
        raise HTTPException(status_code=404, detail="Artifact not found.")

    artifact_path = Path(artifact_path).resolve()

    if not artifact_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Artifact file does not exist. This temporary analysis may have expired.",
        )

    if not artifact_path.is_relative_to(run_dir):
        raise HTTPException(status_code=403, detail="Invalid artifact path.")

    return artifact_path


@app.get("/preview/{run_name}/{artifact_key}")
def preview_artifact(run_name: str, artifact_key: str):
    artifact_path = resolve_run_artifact(run_name, artifact_key)

    if artifact_path.suffix.lower() == ".pdf":
        media_type = "application/pdf"
    elif artifact_path.suffix.lower() == ".json":
        media_type = "application/json"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        artifact_path,
        media_type=media_type,
        filename=artifact_path.name,
        content_disposition_type="inline",
        headers=no_store_headers(),
    )


@app.get("/download/{run_name}/{artifact_key}")
def download_artifact(run_name: str, artifact_key: str):
    block_public_json_artifact(artifact_key)
    result = load_result(run_name)
    target = get_artifact_path(result, artifact_key)

    allowed_root = Path(result["run_dir"]).resolve()
    target_resolved = target.resolve()

    if not target_resolved.is_relative_to(allowed_root):
        raise HTTPException(status_code=403, detail="Artifact outside run directory")

    media_type = "application/octet-stream"

    if target.suffix.lower() == ".pdf":
        media_type = "application/pdf"
    elif target.suffix.lower() == ".json":
        media_type = "application/json"

    return FileResponse(
        target,
        filename=target.name,
        media_type=media_type,
        headers=no_store_headers(),
    )




@app.post("/feedback/{run_name}")
async def submit_feedback(
    request: Request,
    run_name: str,
    feedback_type: str = Form(...),
    message: str = Form(...),
):
    """
    Store private-beta feedback without storing the uploaded drawing.

    Do not include PDF contents, extracted sheet text, or raw results here.
    """
    run_name = safe_run_name(run_name)
    feedback_type = feedback_type.strip()[:80]
    message = message.strip()[:4000]

    if not message:
        raise HTTPException(status_code=400, detail="Feedback message cannot be empty.")

    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

    feedback_record = {
        "feedback_id": uuid.uuid4().hex,
        "run_name": run_name,
        "feedback_type": feedback_type,
        "message": message,
        "created_at": int(time.time()),
        "privacy_note": "No uploaded PDF or raw analysis JSON is stored in this feedback record.",
    }

    feedback_path = FEEDBACK_DIR / f"{feedback_record['feedback_id']}.json"
    feedback_path.write_text(json.dumps(feedback_record, indent=4), encoding="utf-8")

    return templates.TemplateResponse(
        request,
        "feedback_thanks.html",
        {
            "request": request,
            "run_name": run_name,
        },
    )


@app.get("/results/{run_name}")
def reopen_results(request: Request, run_name: str):
    result = load_result(run_name)

    return templates.TemplateResponse(
        request,
        "results.html",
        result_context(request, result),
    )


@app.get("/runs")
def runs_disabled():
    raise HTTPException(
        status_code=410,
        detail="Recent Analyses is disabled in zero-retention mode.",
    )


def delete_ephemeral_path(path_value: str | None) -> None:
    """
    Delete a file or folder only if it is inside the configured ephemeral root.
    """
    if not path_value:
        return

    try:
        target = Path(path_value).resolve()
        ephemeral_root = EPHEMERAL_ROOT.resolve()

        if not target.is_relative_to(ephemeral_root):
            return

        if target.is_file():
            target.unlink(missing_ok=True)
        elif target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
    except Exception:
        pass


def delete_temp_run_folder(run_name: str) -> None:
    """
    Delete all temporary analysis data after package download:
    - uploaded temp PDF
    - normalized temp PDF
    - generated reports
    - generated marked PDFs
    - generated JSON files
    - run folder
    """
    try:
        run_name = safe_run_name(run_name)
        run_dir = (WEB_RUNS_DIR / run_name).resolve()
        result_path = run_dir / "reports" / "single_section_results.json"

        result = {}
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))

        preprocessing = result.get("preprocessing", {})

        delete_ephemeral_path(preprocessing.get("original_pdf"))
        delete_ephemeral_path(preprocessing.get("analysis_pdf"))

        # Delete the whole generated run folder last.
        delete_ephemeral_path(str(run_dir))

    except Exception:
        # Do not leak file/project details into logs.
        pass


@app.post("/download-all-delete/{run_name}")
def download_all_and_delete(run_name: str, background_tasks: BackgroundTasks):
    """
    Create a ZIP package of the available analysis artifacts, return it to the user,
    and delete the temporary analysis folder after the response is sent.

    Zero-retention behavior:
    - report/marked PDF/results are available only for this temporary session
    - after this download finishes, the job folder is removed
    """
    result = load_result(run_name)

    run_dir = Path(result["run_dir"]).resolve()
    reports_dir = run_dir / "reports"

    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Temporary run not found.")

    zip_path = reports_dir / "civcheck_qc_package.zip"
    reports_dir.mkdir(parents=True, exist_ok=True)

    artifacts = result.get("artifacts", {})

    allowed_artifacts = {
        "report_pdf": "qc_report.pdf",
        "marked_pdf": "marked_drawing.pdf",
    }

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for artifact_key, zip_name in allowed_artifacts.items():
            artifact_value = artifacts.get(artifact_key)

            if not artifact_value:
                continue

            artifact_path = Path(artifact_value).resolve()

            if not artifact_path.exists():
                continue

            if not artifact_path.is_relative_to(run_dir):
                continue

            zip_file.write(artifact_path, arcname=zip_name)

        privacy_notice = (
            "CivCheck AI temporary analysis package\n\n"
            "This package was generated from a zero-retention temporary analysis session.\n"
            "The server is configured to delete the temporary job folder after this download response finishes.\n"
            "This automated QC supports, but does not replace, review by a qualified engineer.\n"
        )

        zip_file.writestr("privacy_notice.txt", privacy_notice)

        # Optional debug JSON export for local testing/private beta debugging.
        # Keep disabled for public/customer downloads.
        include_debug_json = os.getenv("CIVCHECK_INCLUDE_DEBUG_JSON", "0") == "1"

        if include_debug_json:
            for json_path in run_dir.rglob("*.json"):
                if not json_path.is_file():
                    continue

                if "__pycache__" in json_path.parts:
                    continue

                # Keep package safe: only include files inside this run folder.
                try:
                    relative_json_path = json_path.resolve().relative_to(run_dir)
                except ValueError:
                    continue

                zip_file.write(
                    json_path,
                    arcname=f"debug/{relative_json_path}",
                )

    background_tasks.add_task(delete_temp_run_folder, run_name)

    return FileResponse(
        zip_path,
        filename="civcheck_qc_package.zip",
        media_type="application/zip",
        background=background_tasks,
        headers=no_store_headers(),
    )


# Override station title logic with direct PDF page text extraction.
# This is more reliable than searching the results JSON.
def build_station_titles(result: dict) -> dict[int, str]:
    """
    Build page titles from station labels found directly in the analysis PDF.

    Example:
    {
        1: "STA. 170+50.00",
        2: "STA. 170+00.00"
    }
    """
    preprocessing = result.get("preprocessing", {})
    analysis_pdf = preprocessing.get("analysis_pdf")

    station_titles: dict[int, str] = {}

    if analysis_pdf:
        pdf_path = Path(analysis_pdf)

        if pdf_path.exists():
            try:
                with fitz.open(pdf_path) as doc:
                    for page_index, page in enumerate(doc, start=1):
                        page_text = page.get_text("text") or ""
                        station = _station_from_text(page_text)

                        if station:
                            station_titles[page_index] = station
            except Exception:
                pass

    return station_titles


def build_finding_page_groups(result: dict) -> list[dict]:
    rows = build_finding_rows(result)
    station_titles = build_station_titles(result)

    groups = {}

    for row in rows:
        page = row.get("page", "—")
        groups.setdefault(page, []).append(row)

    grouped_rows = []

    for page, page_rows in groups.items():
        try:
            page_number = int(page)
        except (TypeError, ValueError):
            page_number = None

        title = (
            station_titles.get(page_number)
            if page_number is not None
            else None
        )

        grouped_rows.append(
            {
                "page": page,
                "title": title or f"Analysis Page {page}",
                "rows": page_rows,
                "count": len(page_rows),
            }
        )

    return grouped_rows
