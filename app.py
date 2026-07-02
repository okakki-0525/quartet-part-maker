from __future__ import annotations

import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from extract_part import extract_to_pdf


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
WORK_ROOT = Path(tempfile.gettempdir()) / "quartet_part_maker"


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def cleanup_old_jobs(max_age_seconds: int = 60 * 60) -> None:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for child in WORK_ROOT.iterdir():
        if child.is_dir() and now - child.stat().st_mtime > max_age_seconds:
            shutil.rmtree(child, ignore_errors=True)


def make_job_dir() -> Path:
    cleanup_old_jobs()
    job_dir = WORK_ROOT / uuid.uuid4().hex
    job_dir.mkdir(parents=True)
    return job_dir


def save_uploads(job_dir: Path) -> list[Path]:
    files = request.files.getlist("images")
    if not files:
        raise ValueError("画像ファイルを選択してください。")

    input_dir = job_dir / "inputs"
    input_dir.mkdir()
    paths: list[Path] = []
    for index, file_storage in enumerate(files, start=1):
        original_name = file_storage.filename or f"image_{index}.jpg"
        if not allowed_file(original_name):
            raise ValueError(f"対応していないファイル形式です: {original_name}")
        safe_name = secure_filename(original_name) or f"image_{index}.jpg"
        path = input_dir / f"{index:03d}_{safe_name}"
        file_storage.save(path)
        paths.append(path)
    return paths


def form_float(name: str, default: float, min_value: float, max_value: float) -> float:
    raw_value = request.form.get(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} の値が不正です。") from exc
    return max(min_value, min(max_value, value))


def build_pdf(input_paths: list[Path], output_path: Path, part: int) -> None:
    vertical_scale = form_float("vertical_scale", 1.3, 1.0, 1.6)
    gap_mm = form_float("gap_mm", 5.0, 0.0, 15.0)
    extract_to_pdf(
        inputs=input_paths,
        output=output_path,
        part=str(part),
        percentile=70.0,
        detect_x_margin_ratio=0.07,
        crop_x_margin_ratio=0.02,
        y_margin_ratio=0.55,
        gap_mm=gap_mm,
        page_width_mm=210.0,
        page_height_mm=297.0,
        page_margin_mm=12.0,
        dpi=200,
        rehearsal_marks=True,
        clean_strength=1.7,
        vertical_scale=vertical_scale,
        preprocess=True,
        preprocess_deskew_angle=2.5,
        preprocess_deskew_step=0.25,
        preprocess_normalize_strength=1.15,
        preprocess_debug_dir=None,
        debug_dir=None,
    )


def send_and_cleanup(path: Path, job_dir: Path, download_name: str):
    response = send_file(path, as_attachment=True, download_name=download_name)
    response.call_on_close(lambda: shutil.rmtree(job_dir, ignore_errors=True))
    return response


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/generate/<int:part>")
def generate_part(part: int):
    if part not in {1, 2, 3, 4}:
        return jsonify({"error": "パートは1から4で指定してください。"}), 400
    job_dir = make_job_dir()
    try:
        input_paths = save_uploads(job_dir)
        output_path = job_dir / f"part{part}.pdf"
        build_pdf(input_paths, output_path, part)
        return send_and_cleanup(output_path, job_dir, f"part{part}.pdf")
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": str(exc)}), 400


@app.post("/generate/all")
def generate_all():
    job_dir = make_job_dir()
    try:
        input_paths = save_uploads(job_dir)
        output_dir = job_dir / "outputs"
        output_dir.mkdir()
        pdf_paths: list[Path] = []
        for part in range(1, 5):
            output_path = output_dir / f"part{part}.pdf"
            build_pdf(input_paths, output_path, part)
            pdf_paths.append(output_path)

        zip_path = job_dir / "parts.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for pdf_path in pdf_paths:
                zip_file.write(pdf_path, arcname=pdf_path.name)
        return send_and_cleanup(zip_path, job_dir, "parts.zip")
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
