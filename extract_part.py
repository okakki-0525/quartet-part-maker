from __future__ import annotations

import argparse
from collections import deque
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps


PARTS = {
    "violin1": 0,
    "vln1": 0,
    "1": 0,
    "violin2": 1,
    "vln2": 1,
    "2": 1,
    "viola": 2,
    "vla": 2,
    "3": 2,
    "violoncello": 3,
    "cello": 3,
    "vc": 3,
    "4": 3,
}


@dataclass(frozen=True)
class Staff:
    top: int
    bottom: int
    center: int


@dataclass(frozen=True)
class System:
    staves: tuple[Staff, Staff, Staff, Staff]


def natural_key(path: Path) -> list[object]:
    return [int(s) if s.isdigit() else s.lower() for s in re.split(r"(\d+)", path.name)]


def parse_inputs(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = sorted(Path().glob(pattern), key=natural_key)
        if matches:
            paths.extend(matches)
        else:
            paths.append(Path(pattern))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            if not path.exists():
                raise FileNotFoundError(path)
            unique.append(path)
            seen.add(resolved)
    return unique



def likely_paper_mask(image: Image.Image) -> np.ndarray:
    arr = np.asarray(image.convert("RGB")).astype(np.int16)
    max_channel = arr.max(axis=2)
    min_channel = arr.min(axis=2)
    saturation_span = max_channel - min_channel
    return (max_channel > 135) & (saturation_span < 85)


def find_content_span(values: np.ndarray, min_fraction: float) -> tuple[int, int] | None:
    active = np.where(values > min_fraction)[0]
    if active.size == 0:
        return None
    return int(active[0]), int(active[-1]) + 1


def detect_paper_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    mask = likely_paper_mask(image)
    row_span = find_content_span(mask.mean(axis=1), 0.18)
    col_span = find_content_span(mask.mean(axis=0), 0.18)
    if row_span is None or col_span is None:
        return None

    width, height = image.size
    left, right = col_span
    top, bottom = row_span
    if (right - left) < width * 0.35 or (bottom - top) < height * 0.35:
        return None

    pad_x = max(8, int(width * 0.01))
    pad_y = max(8, int(height * 0.01))
    return (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(width, right + pad_x),
        min(height, bottom + pad_y),
    )


def crop_to_paper(image: Image.Image) -> Image.Image:
    bbox = detect_paper_bbox(image)
    if bbox is None:
        return image.convert("RGB")
    return image.crop(bbox).convert("RGB")


def deskew_score_image(image: Image.Image, max_angle: float, step: float) -> Image.Image:
    if max_angle <= 0 or step <= 0:
        return image.convert("RGB")

    sample = ImageOps.autocontrast(image.convert("L"))
    max_sample_width = 1200
    if sample.width > max_sample_width:
        scale = max_sample_width / sample.width
        sample = sample.resize((max_sample_width, max(1, int(sample.height * scale))), Image.Resampling.BILINEAR)

    def angle_score(angle: float) -> float:
        rotated = sample.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=255)
        arr = np.asarray(rotated)
        margin_x = int(arr.shape[1] * 0.08)
        margin_y = int(arr.shape[0] * 0.06)
        region = arr[margin_y: arr.shape[0] - margin_y, margin_x: arr.shape[1] - margin_x]
        if region.size == 0:
            return 0.0
        dark = region < 150
        row_scores = dark.mean(axis=1)
        return float(row_scores.var())

    angles = np.arange(-max_angle, max_angle + (step * 0.5), step)
    best_angle = float(max(angles, key=angle_score))
    if abs(best_angle) < step * 0.5:
        return image.convert("RGB")
    return image.rotate(best_angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white").convert("RGB")


def normalize_page_background(image: Image.Image, strength: float) -> Image.Image:
    if strength <= 0:
        return image.convert("RGB")
    gray = ImageOps.grayscale(image)
    arr = np.asarray(gray).astype(np.float32)
    white_point = max(170.0, float(np.percentile(arr, 86)))
    normalized = np.clip(arr * 255.0 / white_point, 0, 255)
    boosted = 255.0 - (255.0 - normalized) * strength
    boosted[normalized > 185] = 255.0
    boosted = np.clip(boosted, 0, 255).astype(np.uint8)
    return Image.fromarray(boosted).convert("RGB")


def preprocess_page_image(
    image: Image.Image,
    enabled: bool,
    deskew_max_angle: float,
    deskew_step: float,
    normalize_strength: float,
) -> Image.Image:
    if not enabled:
        return image.convert("RGB")
    page = crop_to_paper(image)
    page = deskew_score_image(page, max_angle=deskew_max_angle, step=deskew_step)
    page = crop_to_paper(page)
    page = normalize_page_background(page, strength=normalize_strength)
    return page

def row_dark_scores(image: Image.Image, x_margin_ratio: float) -> np.ndarray:
    gray = ImageOps.autocontrast(image.convert("L"))
    arr = np.asarray(gray)
    height, width = arr.shape
    left = int(width * x_margin_ratio)
    right = int(width * (1.0 - x_margin_ratio))
    region = arr[:, left:right]

    # A fixed threshold after autocontrast works well for photographed score pages.
    dark = region < 150
    scores = dark.mean(axis=1)
    kernel = np.ones(3, dtype=float) / 3.0
    return np.convolve(scores, kernel, mode="same")


def find_peak_rows(scores: np.ndarray, percentile: float, min_distance: int) -> list[int]:
    usable = scores[80:-80] if len(scores) > 180 else scores
    threshold = float(np.percentile(usable, percentile))
    peaks: list[tuple[int, float]] = []
    for y in range(1, len(scores) - 1):
        if scores[y] < threshold:
            continue
        if scores[y] < scores[y - 1] or scores[y] < scores[y + 1]:
            continue
        if peaks and y - peaks[-1][0] < min_distance:
            if scores[y] > peaks[-1][1]:
                peaks[-1] = (y, float(scores[y]))
        else:
            peaks.append((y, float(scores[y])))
    return [y for y, _ in peaks]


def cluster_staff_bands(peaks: list[int], max_gap: int, image_height: int) -> list[Staff]:
    if not peaks:
        return []
    bands: list[tuple[int, int]] = []
    start = prev = peaks[0]
    for y in peaks[1:]:
        if y - prev <= max_gap:
            prev = y
        else:
            bands.append((start, prev))
            start = prev = y
    bands.append((start, prev))

    staves: list[Staff] = []
    min_height = max(12, int(image_height * 0.012))
    max_height = max(80, int(image_height * 0.045))
    for top, bottom in bands:
        height = bottom - top
        if min_height <= height <= max_height:
            staves.append(Staff(top=top, bottom=bottom, center=(top + bottom) // 2))
    return staves


def merge_staff_candidates(candidates: list[Staff], image_height: int) -> list[Staff]:
    if not candidates:
        return []
    tolerance = max(10, int(image_height * 0.01))
    merged: list[Staff] = []
    for staff in sorted(candidates, key=lambda s: s.center):
        if not merged or staff.center - merged[-1].center > tolerance:
            merged.append(staff)
            continue
        prev = merged[-1]
        merged[-1] = Staff(
            top=min(prev.top, staff.top),
            bottom=max(prev.bottom, staff.bottom),
            center=(prev.center + staff.center) // 2,
        )
    return merged


def find_systems(image: Image.Image, percentile: float, x_margin_ratio: float) -> list[System]:
    width, height = image.size
    min_distance = max(4, round(height / 350))
    max_gap = max(24, round(height / 42))
    scores = row_dark_scores(image, x_margin_ratio)
    candidate_staves: list[Staff] = []
    for candidate_percentile in (percentile, percentile + 5, percentile - 5, percentile + 10):
        if not 1 <= candidate_percentile <= 99:
            continue
        peaks = find_peak_rows(scores, percentile=candidate_percentile, min_distance=min_distance)
        candidate_staves.extend(cluster_staff_bands(peaks, max_gap=max_gap, image_height=height))
    staves = merge_staff_candidates(candidate_staves, image_height=height)

    systems: list[System] = []
    for i in range(0, len(staves) - 3):
        group = staves[i : i + 4]
        gaps = [group[j + 1].center - group[j].center for j in range(3)]
        if not all(gap > 0 for gap in gaps):
            continue
        median_gap = float(np.median(gaps))
        if median_gap < height * 0.035 or median_gap > height * 0.18:
            continue
        if max(abs(gap - median_gap) for gap in gaps) > median_gap * 0.35:
            continue
        if systems and group[0].center <= systems[-1].staves[-1].center:
            continue
        systems.append(System(tuple(group)))  # type: ignore[arg-type]

    # Prefer non-overlapping 4-staff groups. If the sliding-window test found no
    # groups, fall back to consecutive quartets so the user still gets output.
    if systems:
        compact: list[System] = []
        last_bottom = -1
        for system in systems:
            if system.staves[0].center > last_bottom:
                compact.append(system)
                last_bottom = system.staves[-1].center
        return compact

    return [
        System(tuple(staves[i : i + 4]))  # type: ignore[arg-type]
        for i in range(0, len(staves) - 3, 4)
    ]


def crop_box(
    image: Image.Image,
    system: System,
    part_index: int,
    y_margin_ratio: float,
    x_margin_ratio: float,
) -> tuple[int, int, int, int]:
    width, height = image.size
    staves = system.staves
    staff = staves[part_index]

    if part_index == 0:
        upper_gap = staves[1].center - staves[0].center
        top = staff.top - int(upper_gap * y_margin_ratio)
    else:
        top = (staves[part_index - 1].center + staff.center) // 2

    if part_index == 3:
        lower_gap = staves[3].center - staves[2].center
        bottom = staff.bottom + int(lower_gap * y_margin_ratio)
    else:
        bottom = (staff.center + staves[part_index + 1].center) // 2

    left, right = system_horizontal_bounds(image, system, x_margin_ratio)
    top = max(0, top)
    bottom = min(height, bottom)
    return left, top, right, bottom


def system_horizontal_bounds(image: Image.Image, system: System, fallback_margin_ratio: float) -> tuple[int, int]:
    width, height = image.size
    staves = system.staves
    top_gap = staves[1].center - staves[0].center
    bottom_gap = staves[-1].center - staves[-2].center
    y_top = max(0, staves[0].top - int(top_gap * 0.25))
    y_bottom = min(height, staves[-1].bottom + int(bottom_gap * 0.25))
    region = np.asarray(ImageOps.autocontrast(image.crop((0, y_top, width, y_bottom)).convert("L")))
    dark = region < 150
    column_scores = dark.mean(axis=0)
    active = column_scores > 0.018

    bands: list[tuple[int, int]] = []
    start: int | None = None
    prev: int | None = None
    join_gap = max(12, int(width * 0.012))
    for x, is_active in enumerate(active.tolist()):
        if not is_active:
            continue
        if start is None:
            start = prev = x
        elif prev is not None and x - prev <= join_gap:
            prev = x
        else:
            bands.append((start, prev if prev is not None else start))
            start = prev = x
    if start is not None:
        bands.append((start, prev if prev is not None else start))

    candidates = [band for band in bands if band[1] - band[0] >= width * 0.35]
    if not candidates:
        return int(width * fallback_margin_ratio), int(width * (1.0 - fallback_margin_ratio))

    left, right = max(candidates, key=lambda band: band[1] - band[0])
    pad = max(8, int(width * 0.012))
    return max(0, left - pad), min(width, right + pad)


def clean_score_image(image: Image.Image, strength: float) -> Image.Image:
    if strength <= 0:
        return image.convert("RGB")

    gray = ImageOps.grayscale(image)
    arr = np.asarray(gray).astype(np.float32)
    white_point = max(180.0, float(np.percentile(arr, 82)))
    normalized = np.clip(arr * 255.0 / white_point, 0, 255)
    edge_artifacts = find_dark_edge_artifacts(normalized)
    cleaned = 255.0 - (255.0 - normalized) * strength
    cleaned[normalized > 155] = 255.0
    for start, end in edge_artifacts:
        cleaned[:, start:end] = 255.0
    remove_edge_connected_dark(cleaned)
    cleaned = np.clip(cleaned, 0, 255).astype(np.uint8)
    return Image.fromarray(cleaned).convert("RGB")


def remove_edge_connected_dark(arr: np.ndarray) -> None:
    height, width = arr.shape
    dark = arr < 80
    visited = np.zeros_like(dark, dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    for y in range(height):
        for x in (0, width - 1):
            if dark[y, x] and not visited[y, x]:
                visited[y, x] = True
                queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        arr[y, x] = 255.0
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height and dark[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                queue.append((nx, ny))


def find_dark_edge_artifacts(arr: np.ndarray) -> list[tuple[int, int]]:
    height, width = arr.shape
    very_dark = arr < 80
    dark_columns = very_dark.mean(axis=0) > 0.45
    artifacts: list[tuple[int, int]] = []

    left_end = 0
    while left_end < width and dark_columns[left_end]:
        left_end += 1
    if left_end > max(4, width * 0.01):
        artifacts.append((0, min(width, left_end + max(2, int(width * 0.004)))))

    right_start = width
    while right_start > 0 and dark_columns[right_start - 1]:
        right_start -= 1
    if width - right_start > max(4, width * 0.01):
        artifacts.append((max(0, right_start - max(2, int(width * 0.004))), width))

    return artifacts


def rehearsal_mark_mask(annotation: Image.Image) -> Image.Image:
    gray = ImageOps.autocontrast(annotation.convert("L"))
    arr = np.asarray(gray)
    height, width = arr.shape
    dark = arr < 135
    visited = np.zeros_like(dark, dtype=bool)
    keep = np.zeros_like(dark, dtype=bool)

    def should_keep(min_x: int, min_y: int, max_x: int, max_y: int, pixels: int) -> bool:
        box_w = max_x - min_x + 1
        box_h = max_y - min_y + 1
        if box_w < max(8, width * 0.004) or box_h < max(8, height * 0.18):
            return False
        if box_w > width * 0.08 or box_h > height * 0.95:
            return False
        aspect = box_w / box_h
        if not 0.45 <= aspect <= 2.3:
            return False
        density = pixels / (box_w * box_h)
        if not 0.05 <= density <= 0.65:
            return False
        return True

    ys, xs = np.where(dark)
    for start_y, start_x in zip(ys.tolist(), xs.tolist()):
        if visited[start_y, start_x]:
            continue
        queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
        visited[start_y, start_x] = True
        pixels: list[tuple[int, int]] = []
        min_x = max_x = start_x
        min_y = max_y = start_y
        while queue:
            x, y = queue.popleft()
            pixels.append((x, y))
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height and dark[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    queue.append((nx, ny))

        if should_keep(min_x, min_y, max_x, max_y, len(pixels)):
            pad = max(2, round((max_y - min_y + 1) * 0.08))
            keep[
                max(0, min_y - pad) : min(height, max_y + pad + 1),
                max(0, min_x - pad) : min(width, max_x + pad + 1),
            ] = True

    return Image.fromarray((keep * 255).astype(np.uint8))


def extract_rehearsal_marks(annotation: Image.Image, clean_strength: float) -> Image.Image:
    mask = rehearsal_mark_mask(annotation)
    cleaned = clean_score_image(annotation, clean_strength)
    result = Image.new("RGB", annotation.size, "white")
    result.paste(cleaned, (0, 0), mask)
    return result


def crop_part(
    image: Image.Image,
    system: System,
    part_index: int,
    y_margin_ratio: float,
    x_margin_ratio: float,
    rehearsal_marks: bool,
    clean_strength: float,
) -> Image.Image:
    left, top, right, bottom = crop_box(
        image,
        system,
        part_index,
        y_margin_ratio=y_margin_ratio,
        x_margin_ratio=x_margin_ratio,
    )
    part_crop = clean_score_image(image.crop((left, top, right, bottom)), clean_strength)
    if not rehearsal_marks:
        return part_crop

    staves = system.staves
    first_gap = staves[1].center - staves[0].center
    annotation_top = max(0, staves[0].top - int(first_gap * y_margin_ratio))
    annotation_bottom = max(annotation_top, staves[0].top - max(3, int(first_gap * 0.10)))
    if annotation_bottom - annotation_top < max(8, int(first_gap * 0.20)):
        return part_crop

    if part_index == 0 and top <= annotation_top + 3:
        return part_crop

    annotation = extract_rehearsal_marks(
        image.crop((left, annotation_top, right, annotation_bottom)),
        clean_strength=clean_strength,
    )
    spacer = max(6, int(first_gap * 0.10))
    combined = Image.new("RGB", (part_crop.width, annotation.height + spacer + part_crop.height), "white")
    combined.paste(annotation.convert("RGB"), (0, 0))
    combined.paste(part_crop.convert("RGB"), (0, annotation.height + spacer))
    return combined


def mm_to_px(mm: float, dpi: int) -> int:
    return max(1, round(mm / 25.4 * dpi))


def compose_pages(
    crops: list[Image.Image],
    page_width_mm: float,
    page_height_mm: float,
    dpi: int,
    margin_mm: float,
    gap_mm: float,
    vertical_scale: float,
) -> list[Image.Image]:
    width = mm_to_px(page_width_mm, dpi)
    height = mm_to_px(page_height_mm, dpi)
    margin = mm_to_px(margin_mm, dpi)
    gap = mm_to_px(gap_mm, dpi)
    available_width = width - margin * 2

    resized: list[Image.Image] = []
    for crop in crops:
        scale = available_width / crop.width
        resized.append(
            crop.resize(
                (available_width, max(1, int(crop.height * scale * vertical_scale))),
                Image.Resampling.LANCZOS,
            )
        )

    pages: list[Image.Image] = []
    page = Image.new("RGB", (width, height), "white")
    y = margin
    for crop in resized:
        if y > margin and y + crop.height > height - margin:
            pages.append(page)
            page = Image.new("RGB", (width, height), "white")
            y = margin
        page.paste(crop.convert("RGB"), (margin, y))
        y += crop.height + gap
    pages.append(page)
    return pages


def write_debug(image: Image.Image, systems: list[System], output: Path) -> None:
    debug = image.convert("RGB")
    draw = ImageDraw.Draw(debug)
    colors = ["red", "orange", "green", "blue"]
    for system in systems:
        for i, staff in enumerate(system.staves):
            draw.rectangle((0, staff.top, image.width - 1, staff.bottom), outline=colors[i], width=3)
            draw.line((0, staff.center, image.width - 1, staff.center), fill=colors[i], width=1)
    debug.save(output)


def extract_to_pdf(
    inputs: list[Path],
    output: Path,
    part: str,
    percentile: float,
    detect_x_margin_ratio: float,
    crop_x_margin_ratio: float,
    y_margin_ratio: float,
    gap_mm: float,
    page_width_mm: float,
    page_height_mm: float,
    page_margin_mm: float,
    dpi: int,
    rehearsal_marks: bool,
    clean_strength: float,
    vertical_scale: float,
    preprocess: bool,
    preprocess_deskew_angle: float,
    preprocess_deskew_step: float,
    preprocess_normalize_strength: float,
    preprocess_debug_dir: Path | None,
    debug_dir: Path | None,
) -> None:
    part_key = part.lower()
    if part_key not in PARTS:
        valid = ", ".join(sorted(k for k in PARTS if not k.isdigit()))
        raise ValueError(f"unknown part: {part}. Use one of: {valid}")
    part_index = PARTS[part_key]

    crops: list[Image.Image] = []
    for input_path in inputs:
        image = Image.open(input_path).convert("RGB")
        image = preprocess_page_image(
            image,
            enabled=preprocess,
            deskew_max_angle=preprocess_deskew_angle,
            deskew_step=preprocess_deskew_step,
            normalize_strength=preprocess_normalize_strength,
        )
        if preprocess_debug_dir is not None:
            preprocess_debug_dir.mkdir(parents=True, exist_ok=True)
            image.save(preprocess_debug_dir / f"{input_path.stem}_preprocessed.jpg")
        systems = find_systems(image, percentile=percentile, x_margin_ratio=detect_x_margin_ratio)
        if not systems:
            raise RuntimeError(f"no systems detected in {input_path}")
        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            write_debug(image, systems, debug_dir / f"{input_path.stem}_debug.jpg")
        crops.extend(
            [
                crop_part(
                    image,
                    system,
                    part_index,
                    y_margin_ratio=y_margin_ratio,
                    x_margin_ratio=crop_x_margin_ratio,
                    rehearsal_marks=rehearsal_marks,
                    clean_strength=clean_strength,
                )
            for system in systems
            ]
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    pages = compose_pages(
        crops,
        page_width_mm=page_width_mm,
        page_height_mm=page_height_mm,
        dpi=dpi,
        margin_mm=page_margin_mm,
        gap_mm=gap_mm,
        vertical_scale=vertical_scale,
    )
    first, rest = pages[0], pages[1:]
    first.save(output, "PDF", resolution=float(dpi), save_all=True, append_images=rest)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract one part from photographed string-quartet score pages and save it as a PDF."
    )
    parser.add_argument("inputs", nargs="+", help="Input image paths or glob patterns, for example p*.jpg")
    parser.add_argument("-p", "--part", default="violin1", help="violin1, violin2, viola, or violoncello")
    parser.add_argument("-o", "--output", default="part.pdf", help="Output PDF path")
    parser.add_argument("--percentile", type=float, default=70.0, help="Staff-line detection sensitivity")
    parser.add_argument("--detect-x-margin", type=float, default=0.07, help="Horizontal margin ratio used only for staff detection")
    parser.add_argument("--x-margin", type=float, default=0.02, help="Horizontal crop margin ratio")
    parser.add_argument("--y-margin", type=float, default=0.55, help="Extra top/bottom margin for outer parts")
    parser.add_argument("--gap-mm", type=float, default=10.0, help="Vertical gap between extracted systems, in mm")
    parser.add_argument("--page-width-mm", type=float, default=210.0, help="Output page width in mm")
    parser.add_argument("--page-height-mm", type=float, default=297.0, help="Output page height in mm")
    parser.add_argument("--page-margin-mm", type=float, default=12.0, help="Output page margin in mm")
    parser.add_argument("--dpi", type=int, default=200, help="Output PDF raster resolution")
    parser.add_argument("--clean-strength", type=float, default=1.7, help="Whitening/contrast strength for extracted score images; use 0 to disable")
    parser.add_argument("--vertical-scale", type=float, default=1.0, help="Stretch extracted systems vertically without changing their width")
    parser.add_argument("--no-preprocess", action="store_true", help="Disable page-level preprocessing before part extraction")
    parser.add_argument("--preprocess-deskew-angle", type=float, default=2.5, help="Maximum page deskew angle in degrees")
    parser.add_argument("--preprocess-deskew-step", type=float, default=0.25, help="Deskew search step in degrees")
    parser.add_argument("--preprocess-normalize-strength", type=float, default=1.15, help="Page-level background normalization strength before extraction")
    parser.add_argument("--preprocess-debug-dir", type=Path, help="Directory for preprocessed page preview images")
    parser.add_argument("--no-rehearsal-marks", action="store_true", help="Do not copy top-system rehearsal-mark area to every part")
    parser.add_argument("--debug-dir", type=Path, help="Directory for detection preview images")
    args = parser.parse_args()

    inputs = parse_inputs(args.inputs)
    extract_to_pdf(
        inputs=inputs,
        output=Path(args.output),
        part=args.part,
        percentile=args.percentile,
        detect_x_margin_ratio=args.detect_x_margin,
        crop_x_margin_ratio=args.x_margin,
        y_margin_ratio=args.y_margin,
        gap_mm=args.gap_mm,
        page_width_mm=args.page_width_mm,
        page_height_mm=args.page_height_mm,
        page_margin_mm=args.page_margin_mm,
        dpi=args.dpi,
        rehearsal_marks=not args.no_rehearsal_marks,
        clean_strength=args.clean_strength,
        vertical_scale=args.vertical_scale,
        preprocess=not args.no_preprocess,
        preprocess_deskew_angle=args.preprocess_deskew_angle,
        preprocess_deskew_step=args.preprocess_deskew_step,
        preprocess_normalize_strength=args.preprocess_normalize_strength,
        preprocess_debug_dir=args.preprocess_debug_dir,
        debug_dir=args.debug_dir,
    )
    print(f"Wrote {args.output} from {len(inputs)} input image(s).")


if __name__ == "__main__":
    main()
