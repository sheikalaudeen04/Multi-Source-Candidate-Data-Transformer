"""Minimal local web UI around the existing CLI pipeline.

This is strictly an input/output wrapper, same role as cli.py: it gathers
input files (calling the same extractor functions cli.py uses — directly,
rather than through cli.py's collect_batches(), since that only supports one
file per source kind and this UI needs to support multiple résumé/notes
files in one run), calls the same run_pipeline() function, and renders the
result. No pipeline logic lives here.
"""
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from flask import Flask, render_template, request, send_file
from werkzeug.utils import secure_filename

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cli import run_pipeline  # noqa: E402
from src.detect import detect_file_source  # noqa: E402
from src.extractors import csv_extractor, ats_json_extractor, resume_extractor, notes_extractor  # noqa: E402
from src.projector import DEFAULT_CONFIG  # noqa: E402

from render import render_profiles  # noqa: E402

load_dotenv()

app = Flask(__name__)

OUTPUT_DIR = Path(tempfile.gettempdir()) / "eightfold_ui_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


def _s3_client():
    return boto3.client("s3", region_name=os.environ.get("AWS_DEFAULT_REGION"))


def _bucket_name() -> str:
    bucket = os.environ.get("S3_BUCKET_NAME")
    if not bucket:
        raise RuntimeError("S3_BUCKET_NAME is not set — check your .env file.")
    return bucket


def _upload_and_download(s3, bucket: str, run_id: str, files, local_dir: Path, key_subdir: str | None = None) -> list[Path]:
    """Uploads each file to S3 under uploads/{run_id}/[{key_subdir}/]{filename},
    then downloads it back into a local temp dir so the existing extractors
    can keep reading plain local file paths unchanged."""
    local_paths = []
    for f in files:
        filename = secure_filename(f.filename)
        key = f"uploads/{run_id}/{filename}" if not key_subdir else f"uploads/{run_id}/{key_subdir}/{filename}"

        s3.put_object(Bucket=bucket, Key=key, Body=f.read())

        local_path = local_dir / filename
        s3.download_file(bucket, key, str(local_path))
        local_paths.append(local_path)
    return local_paths


def _gather_batches(local_paths: list[Path]) -> list[list]:
    """Classifies each uploaded file by kind and runs it through the same
    extractor cli.py would use. Every CSV/ATS-JSON file contributes all of
    its rows/records; every résumé/notes file contributes its own batch —
    so multiple résumés or notes files in one run are fully supported, not
    collapsed down to "first match wins"."""
    raw_batches: list[list] = []
    for path in local_paths:
        kind = detect_file_source(str(path))
        if kind == "recruiter_csv":
            raw_batches.extend(csv_extractor.extract(str(path)))
        elif kind == "ats_json":
            raw_batches.extend(ats_json_extractor.extract(str(path)))
        elif kind == "resume":
            batch = resume_extractor.extract(str(path))
            if batch:
                raw_batches.append(batch)
        elif kind == "notes":
            batch = notes_extractor.extract(str(path))
            if batch:
                raw_batches.append(batch)

    return raw_batches


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run():
    run_id = uuid.uuid4().hex[:10]

    mode = request.form.get("mode", "default")  # "default" | "custom"
    source_files = [f for f in request.files.getlist("source_files") if f and f.filename]
    config_file = request.files.get("config_file")

    if not source_files:
        return render_template("index.html", error="Please select at least one input file.", mode=mode)
    if mode == "custom" and not (config_file and config_file.filename):
        return render_template("index.html", error="Custom config mode selected, but no config file was uploaded.", mode=mode)

    try:
        s3 = _s3_client()
        bucket = _bucket_name()
    except (BotoCoreError, ClientError, RuntimeError) as e:
        return render_template("index.html", error=f"AWS configuration error: {e}", mode=mode)

    local_dir = Path(tempfile.mkdtemp(prefix=f"eightfold_{run_id}_"))

    try:
        local_paths = _upload_and_download(s3, bucket, run_id, source_files, local_dir)
        config_path = None
        if mode == "custom":
            config_path = _upload_and_download(s3, bucket, run_id, [config_file], local_dir, key_subdir="config")[0]
    except (BotoCoreError, ClientError) as e:
        return render_template("index.html", error=f"S3 upload/download failed: {e}", mode=mode)
    except OSError as e:
        return render_template("index.html", error=f"Local file handling failed: {e}", mode=mode)

    config = DEFAULT_CONFIG
    if mode == "custom":
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return render_template("index.html", error=f"Could not parse config file: {e}", mode=mode)

    try:
        raw_batches = _gather_batches(local_paths)
        # run_pipeline returns the *internal* candidate_id alongside each
        # result (result_candidate_ids[i] for results[i]) and the full
        # ledger -- both independent of what the active config chose to
        # keep in the projected output, so the ledger can always be
        # associated with the right profile, even in custom-config mode.
        results, ledger, result_candidate_ids, warnings = run_pipeline(raw_batches, config, verbose=False)
    except Exception as e:
        # mirrors the CLI pipeline's "never crash on bad input" philosophy --
        # surface it as a readable message instead of a stack trace
        return render_template("index.html", error=f"Pipeline run failed: {e}", mode=mode)

    output_json = json.dumps(results, indent=2, default=str)
    (OUTPUT_DIR / f"{run_id}.json").write_text(output_json, encoding="utf-8")

    ledger_by_id: dict[str, list] = {}
    for entry in ledger:
        ledger_by_id.setdefault(entry.candidate_id, []).append(entry)
    ledger_per_result = [ledger_by_id.get(cid, []) for cid in result_candidate_ids]

    pretty_html = render_profiles(results, ledger_per_result)
    warning = "; ".join(warnings) if warnings else None

    try:
        s3.put_object(Bucket=bucket, Key=f"uploads/{run_id}/output.json", Body=output_json.encode("utf-8"))
    except (BotoCoreError, ClientError) as e:
        s3_warning = f"Run succeeded, but saving output.json to S3 failed: {e}"
        warning = f"{warning}; {s3_warning}" if warning else s3_warning

    return render_template(
        "index.html", result=output_json, pretty_html=pretty_html,
        run_id=run_id, mode=mode, warning=warning,
    )


@app.route("/download/<run_id>")
def download(run_id):
    output_path = OUTPUT_DIR / f"{run_id}.json"
    if not output_path.exists():
        return "Output not found for this run.", 404
    return send_file(output_path, as_attachment=True, download_name=f"profiles_{run_id}.json", mimetype="application/json")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
