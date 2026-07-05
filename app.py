from __future__ import annotations

import gc
import json
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from PIL import Image

from extract_part import PARTS, crop_part, find_systems, mm_to_px, preprocess_page_image


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
WORK_ROOT = Path(tempfile.gettempdir()) / "quartet_part_maker"

# Web hosting on Render is much slower than local execution. Keep preprocessing
# light and resize photos before any expensive image work.
WEB_MAX_IMAGE_SIDE = 2200
WEB_DESKEW_ANGLE = 0.0
WEB_DESKEW_STEP = 1.0
WEB_NORMALIZE_STRENGTH = 1.15


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


def resize_for_web(image: Image.Image) -> Image.Image:
    width, height = image.size
    longest_side = max(width, height)
    if longest_side <= WEB_MAX_IMAGE_SIDE:
        return image.convert("RGB")
    scale = WEB_MAX_IMAGE_SIDE / longest_side
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS).convert("RGB")


def form_float(name: str, default: float, min_value: float, max_value: float) -> float:
    raw_value = request.form.get(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} の値が不正です。") from exc
    return max(min_value, min(max_value, value))


def memory_job_dir(session_id: str) -> Path:
    if not session_id or not all(char.isalnum() for char in session_id):
        raise ValueError("session id is invalid")
    return WORK_ROOT / session_id


def memory_state_path(job_dir: Path) -> Path:
    return job_dir / "state.json"


def load_memory_state(job_dir: Path) -> dict:
    state_path = memory_state_path(job_dir)
    if not state_path.exists():
        raise ValueError("省メモリモードの作業データが見つかりません。最初からやり直してください。")
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_memory_state(job_dir: Path, state: dict) -> None:
    memory_state_path(job_dir).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def make_memory_state(part: int, vertical_scale: float, gap_mm: float) -> dict:
    dpi = 200
    page_width_mm = 210.0
    page_height_mm = 297.0
    margin_mm = 12.0
    page_width_px = mm_to_px(page_width_mm, dpi)
    page_height_px = mm_to_px(page_height_mm, dpi)
    margin_px = mm_to_px(margin_mm, dpi)
    return {
        "part": part,
        "vertical_scale": vertical_scale,
        "gap_mm": gap_mm,
        "dpi": dpi,
        "page_width_px": page_width_px,
        "page_height_px": page_height_px,
        "margin_px": margin_px,
        "gap_px": mm_to_px(gap_mm, dpi),
        "available_width_px": page_width_px - margin_px * 2,
        "page_number": 1,
        "current_y": margin_px,
        "current_count": 0,
        "crop_serial": 1,
        "uploaded_pages": 0,
        "extracted_systems": 0,
        "ready_pages": [],
    }


def current_crop_dir(job_dir: Path) -> Path:
    path = job_dir / "current"
    path.mkdir(exist_ok=True)
    return path


def pages_dir(job_dir: Path) -> Path:
    path = job_dir / "pages"
    path.mkdir(exist_ok=True)
    return path


def resize_crop_for_memory_pdf(crop: Image.Image, state: dict) -> Image.Image:
    available_width = int(state["available_width_px"])
    scale = available_width / crop.width
    height = max(1, int(crop.height * scale * float(state["vertical_scale"])))
    return crop.resize((available_width, height), Image.Resampling.LANCZOS).convert("RGB")


def finalize_memory_page(job_dir: Path, state: dict) -> dict | None:
    if int(state["current_count"]) == 0:
        return None

    page_number = int(state["page_number"])
    page = Image.new("RGB", (int(state["page_width_px"]), int(state["page_height_px"])), "white")
    y = int(state["margin_px"])
    crop_paths = sorted(current_crop_dir(job_dir).glob("*.jpg"))
    for crop_path in crop_paths:
        with Image.open(crop_path) as crop:
            page.paste(crop.convert("RGB"), (int(state["margin_px"]), y))
            y += crop.height + int(state["gap_px"])

    output_path = pages_dir(job_dir) / f"part{state['part']}_page{page_number}.pdf"
    page.save(output_path, "PDF", resolution=float(state["dpi"]))
    page.close()

    for crop_path in crop_paths:
        crop_path.unlink(missing_ok=True)

    ready_page = {
        "page": page_number,
        "filename": output_path.name,
        "download_name": f"part{state['part']}_page{page_number}.pdf",
    }
    state["ready_pages"].append(ready_page)
    state["page_number"] = page_number + 1
    state["current_y"] = int(state["margin_px"])
    state["current_count"] = 0
    return ready_page


def add_crop_to_memory_page(job_dir: Path, state: dict, crop: Image.Image) -> bool:
    resized = resize_crop_for_memory_pdf(crop, state)
    page_bottom = int(state["page_height_px"]) - int(state["margin_px"])
    current_y = int(state["current_y"])
    overflowed = False

    if int(state["current_count"]) > 0 and current_y + resized.height > page_bottom:
        finalize_memory_page(job_dir, state)
        overflowed = True
        current_y = int(state["current_y"])

    crop_path = current_crop_dir(job_dir) / f"{int(state['crop_serial']):05d}.jpg"
    resized.save(crop_path, quality=90)
    resized.close()
    state["crop_serial"] = int(state["crop_serial"]) + 1
    state["current_y"] = current_y + resized.height + int(state["gap_px"])
    state["current_count"] = int(state["current_count"]) + 1
    return overflowed


def process_memory_uploads(job_dir: Path, state: dict) -> tuple[int, bool]:
    files = request.files.getlist("images")
    if not files:
        raise ValueError("画像ファイルを選択してください。")

    processed_systems = 0
    overflowed = False
    part_index = PARTS[str(state["part"])]

    uploaded_count = 0
    for file_storage in files:
        original_name = file_storage.filename or "image.jpg"
        if not allowed_file(original_name):
            raise ValueError(f"対応していないファイル形式です: {original_name}")

        with Image.open(file_storage.stream) as opened:
            image = resize_for_web(opened.convert("RGB"))
        image = preprocess_page_image(
            image,
            enabled=True,
            deskew_max_angle=WEB_DESKEW_ANGLE,
            deskew_step=WEB_DESKEW_STEP,
            normalize_strength=WEB_NORMALIZE_STRENGTH,
        )
        systems = find_systems(image, percentile=70.0, x_margin_ratio=0.07)
        if not systems:
            image.close()
            raise RuntimeError(f"段を検出できませんでした: {original_name}")

        for system in systems:
            crop = crop_part(
                image,
                system,
                part_index,
                y_margin_ratio=0.55,
                x_margin_ratio=0.02,
                rehearsal_marks=True,
                clean_strength=1.7,
            )
            overflowed = add_crop_to_memory_page(job_dir, state, crop) or overflowed
            crop.close()
            processed_systems += 1

        image.close()
        uploaded_count += 1
        gc.collect()

    state["uploaded_pages"] = int(state.get("uploaded_pages", 0)) + uploaded_count
    state["extracted_systems"] = int(state.get("extracted_systems", 0)) + processed_systems
    return processed_systems, overflowed


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/memory/start")
def memory_start():
    part = int(form_float("part", 1, 1, 4))
    vertical_scale = form_float("vertical_scale", 1.3, 1.0, 1.6)
    gap_mm = form_float("gap_mm", 5.0, 0.0, 15.0)
    job_dir = make_job_dir()
    state = make_memory_state(part, vertical_scale, gap_mm)
    save_memory_state(job_dir, state)
    return jsonify(
        {
            "session_id": job_dir.name,
            "message": f"省メモリモードを開始しました。パート{part}の画像を順番に追加してください。",
            "state": state,
        }
    )


@app.post("/memory/<session_id>/add")
def memory_add(session_id: str):
    job_dir = memory_job_dir(session_id)
    try:
        state = load_memory_state(job_dir)
        processed_systems, overflowed = process_memory_uploads(job_dir, state)
        save_memory_state(job_dir, state)
        notices = [f"{processed_systems}段を処理しました。"]
        if overflowed:
            notices.append("今回の画像の中に、現在のページに入りきらない段があったので、次ページの先頭に入れます。")
        if state["ready_pages"]:
            latest = state["ready_pages"][-1]
            notices.append(f"パート{state['part']}の{latest['page']}ページ目が作れるようになりました。")
        return jsonify({"message": " ".join(notices), "state": state})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/memory/<session_id>/finish")
def memory_finish(session_id: str):
    job_dir = memory_job_dir(session_id)
    try:
        state = load_memory_state(job_dir)
        ready_page = finalize_memory_page(job_dir, state)
        save_memory_state(job_dir, state)
        if ready_page is None:
            message = "現在のページにはまだ段がありません。"
        else:
            message = f"最後のページとして、パート{state['part']}の{ready_page['page']}ページ目が作れるようになりました。"
        return jsonify({"message": message, "state": state})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/memory/<session_id>/download/<int:page_number>")
def memory_download(session_id: str, page_number: int):
    job_dir = memory_job_dir(session_id)
    state = load_memory_state(job_dir)
    for ready_page in state["ready_pages"]:
        if int(ready_page["page"]) == page_number:
            if ready_page.get("discarded"):
                break
            path = pages_dir(job_dir) / ready_page["filename"]
            if not path.exists():
                break
            return send_file(path, as_attachment=True, download_name=ready_page["download_name"])
    return jsonify({"error": "指定されたPDFページが見つかりません。"}), 404


@app.post("/memory/<session_id>/discard-latest")
def memory_discard_latest(session_id: str):
    job_dir = memory_job_dir(session_id)
    try:
        state = load_memory_state(job_dir)
        ready_pages = state.get("ready_pages", [])
        for ready_page in reversed(ready_pages):
            if ready_page.get("discarded"):
                continue
            path = pages_dir(job_dir) / ready_page["filename"]
            path.unlink(missing_ok=True)
            ready_page["discarded"] = True
            save_memory_state(job_dir, state)
            return jsonify({"message": "現在のパート譜を破棄しました。", "state": state})
        return jsonify({"message": "破棄するパート譜はありません。", "state": state})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/memory/<session_id>/clear")
def memory_clear(session_id: str):
    job_dir = memory_job_dir(session_id)
    shutil.rmtree(job_dir, ignore_errors=True)
    return jsonify({"message": "省メモリモードの作業データを削除しました。"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
