from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps, ImageStat

_ALLOWED_PROFILES = {"balanced", "text_priority", "tables_priority", "diagrams_priority", "safe"}
_MAX_PIXELS = 32_000_000

_PRESETS = {
    "safe": {
        "contrast": 1.08,
        "sharpness": 1.08,
        "denoise": 1,
        "background_cleanup": 0.10,
        "bleed_reduction": 0.05,
        "threshold_bias": 0,
    },
    "balanced": {
        "contrast": 1.18,
        "sharpness": 1.22,
        "denoise": 1,
        "background_cleanup": 0.22,
        "bleed_reduction": 0.12,
        "threshold_bias": 3,
    },
    "text_priority": {
        "contrast": 1.28,
        "sharpness": 1.34,
        "denoise": 1,
        "background_cleanup": 0.30,
        "bleed_reduction": 0.18,
        "threshold_bias": 6,
    },
    "tables_priority": {
        "contrast": 1.24,
        "sharpness": 1.40,
        "denoise": 1,
        "background_cleanup": 0.20,
        "bleed_reduction": 0.10,
        "threshold_bias": 2,
    },
    "diagrams_priority": {
        "contrast": 1.18,
        "sharpness": 1.45,
        "denoise": 0,
        "background_cleanup": 0.15,
        "bleed_reduction": 0.05,
        "threshold_bias": 0,
    },
}


@dataclass(frozen=True)
class EnhancementResult:
    visual_png: bytes
    ocr_png: bytes
    diff_png: bytes
    metrics_before: dict
    metrics_after: dict
    fidelity: dict
    profile: str
    params: dict
    suggested_profile: str


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, result))


def _open_image(data: bytes) -> Image.Image:
    image = Image.open(BytesIO(data))
    image.load()
    if image.width * image.height > _MAX_PIXELS:
        raise ValueError("source page is too large for cleanup")
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    return image


def _png(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _gray(image: Image.Image) -> Image.Image:
    return ImageOps.grayscale(image)


def _edge_score(gray: Image.Image) -> float:
    sample = gray.copy()
    sample.thumbnail((900, 1200))
    edges = sample.filter(ImageFilter.FIND_EDGES)
    stat = ImageStat.Stat(edges)
    return round(min(100.0, float(stat.mean[0]) * 2.5), 2)


def quality_metrics(image: Image.Image) -> dict:
    gray = _gray(image)
    sample = gray.copy()
    sample.thumbnail((900, 1200))
    stat = ImageStat.Stat(sample)
    contrast = min(100.0, float(stat.stddev[0]) * 2.3)
    sharpness = _edge_score(sample)
    hist = sample.histogram()
    total = max(1, sum(hist))
    background = 100.0 * sum(hist[235:]) / total
    dark = 100.0 * sum(hist[:90]) / total
    mid = 100.0 * sum(hist[90:235]) / total
    noise_ref = sample.filter(ImageFilter.MedianFilter(3))
    noise = ImageStat.Stat(ImageChops.difference(sample, noise_ref)).mean[0]
    noise_score = max(0.0, min(100.0, 100.0 - float(noise) * 8.0))
    overall = (
        contrast * 0.28
        + sharpness * 0.30
        + min(100.0, background * 1.5) * 0.14
        + noise_score * 0.28
    )
    return {
        "contrast": round(contrast, 2),
        "sharpness": round(sharpness, 2),
        "background_cleanliness": round(background, 2),
        "dark_ink_ratio": round(dark, 2),
        "mid_tone_ratio": round(mid, 2),
        "noise_cleanliness": round(noise_score, 2),
        "overall": round(max(0.0, min(100.0, overall)), 2),
    }


def suggest_profile(metrics: dict) -> str:
    if float(metrics.get("overall") or 0) >= 78:
        return "safe"
    if float(metrics.get("sharpness") or 0) < 34:
        return "diagrams_priority"
    if float(metrics.get("contrast") or 0) < 42:
        return "text_priority"
    if float(metrics.get("background_cleanliness") or 0) < 55:
        return "balanced"
    return "safe"


def _normalized_region(raw: Any) -> tuple[float, float, float, float] | None:
    if raw in (None, {}, []):
        return None
    if not isinstance(raw, dict):
        raise ValueError("region must be an object")
    x = _clamp(raw.get("x"), 0.0, 0.97, 0.0)
    y = _clamp(raw.get("y"), 0.0, 0.97, 0.0)
    width = _clamp(raw.get("width"), 0.03, 1.0 - x, 1.0 - x)
    height = _clamp(raw.get("height"), 0.03, 1.0 - y, 1.0 - y)
    return (x, y, width, height)


def normalize_params(profile: str, raw: dict | None = None) -> dict:
    if profile not in _ALLOWED_PROFILES:
        raise ValueError("unsupported cleanup profile")
    base = dict(_PRESETS[profile])
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValueError("cleanup params must be an object")
    allowed = {
        "contrast",
        "sharpness",
        "denoise",
        "background_cleanup",
        "bleed_reduction",
        "threshold_bias",
        "deskew",
        "region_aware",
        "region",
    }
    unsupported = set(raw) - allowed
    if unsupported:
        raise ValueError("unsupported cleanup params: " + ",".join(sorted(unsupported)))
    base["contrast"] = _clamp(raw.get("contrast", base["contrast"]), 1.0, 1.6, base["contrast"])
    base["sharpness"] = _clamp(raw.get("sharpness", base["sharpness"]), 1.0, 1.8, base["sharpness"])
    base["denoise"] = int(_clamp(raw.get("denoise", base["denoise"]), 0, 2, base["denoise"]))
    base["background_cleanup"] = _clamp(
        raw.get("background_cleanup", base["background_cleanup"]),
        0.0,
        0.45,
        base["background_cleanup"],
    )
    base["bleed_reduction"] = _clamp(
        raw.get("bleed_reduction", base["bleed_reduction"]),
        0.0,
        0.35,
        base["bleed_reduction"],
    )
    base["threshold_bias"] = int(_clamp(raw.get("threshold_bias", base["threshold_bias"]), -10, 12, base["threshold_bias"]))
    base["deskew"] = bool(raw.get("deskew", False))
    base["region_aware"] = bool(raw.get("region_aware", True))
    base["region"] = _normalized_region(raw.get("region"))
    return base


def _projection_score(gray: Image.Image) -> float:
    sample = gray.copy()
    sample.thumbnail((700, 900))
    if sample.width < 10 or sample.height < 10:
        return 0.0
    px = sample.load()
    rows = []
    for y in range(sample.height):
        count = 0
        for x in range(sample.width):
            if px[x, y] < 180:
                count += 1
        rows.append(count)
    mean = sum(rows) / max(1, len(rows))
    return sum((v - mean) ** 2 for v in rows) / max(1, len(rows))


def estimate_deskew_angle(image: Image.Image) -> float:
    gray = _gray(image)
    baseline = _projection_score(gray)
    best_angle = 0.0
    best_score = baseline
    for angle in (-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0):
        rotated = gray.rotate(angle, resample=Image.Resampling.BILINEAR, expand=False, fillcolor=255)
        score = _projection_score(rotated)
        if score > best_score:
            best_score = score
            best_angle = angle
    if baseline <= 0 or best_score < baseline * 1.08:
        return 0.0
    return best_angle


def _cleanup_luminance(gray: Image.Image, params: dict, *, ocr: bool) -> Image.Image:
    work = gray
    if params["denoise"] >= 1:
        work = work.filter(ImageFilter.MedianFilter(3))
    if params["denoise"] >= 2:
        work = work.filter(ImageFilter.MedianFilter(3))
    work = ImageOps.autocontrast(work, cutoff=(0.5, 0.5))
    work = ImageEnhance.Contrast(work).enhance(params["contrast"] + (0.08 if ocr else 0.0))
    work = ImageEnhance.Sharpness(work).enhance(params["sharpness"] + (0.08 if ocr else 0.0))

    bg = float(params["background_cleanup"])
    bleed = float(params["bleed_reduction"])
    bias = int(params["threshold_bias"])
    lut = []
    for value in range(256):
        v = value
        if bg:
            start = int(205 - bg * 35)
            if v >= start:
                v = int(v + (255 - v) * min(0.85, bg * 1.8))
        if bleed and 120 < v < 220:
            v = int(v + (220 - v) * min(0.65, bleed * 1.5))
        if ocr:
            pivot = 196 + bias
            if v >= pivot:
                v = min(255, int(v + (255 - v) * 0.75))
            elif v <= pivot - 70:
                v = max(0, int(v * 0.82))
        lut.append(max(0, min(255, v)))
    return work.point(lut)


def _apply_region(base: Image.Image, enhanced: Image.Image, region: tuple[float, float, float, float] | None) -> Image.Image:
    if not region:
        return enhanced
    x, y, w, h = region
    box = (
        round(base.width * x),
        round(base.height * y),
        round(base.width * (x + w)),
        round(base.height * (y + h)),
    )
    result = base.copy()
    result.paste(enhanced.crop(box), box)
    return result


def _visual_enhance(image: Image.Image, params: dict, deskew_angle: float) -> Image.Image:
    original = image.convert("RGB")
    work = original
    if deskew_angle:
        work = work.rotate(
            deskew_angle,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=(255, 255, 255),
        )
    gray = _gray(work)
    lum = _cleanup_luminance(gray, params, ocr=False)
    if params["region_aware"]:
        mild = ImageEnhance.Sharpness(lum).enhance(1.05)
        lum = Image.blend(lum, mild, 0.35)
    rgb = Image.merge("RGB", (lum, lum, lum))
    return _apply_region(original, rgb, params["region"])


def _ocr_enhance(image: Image.Image, params: dict, deskew_angle: float) -> Image.Image:
    gray = _gray(image)
    if deskew_angle:
        gray = gray.rotate(
            deskew_angle,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=255,
        )
    enhanced = _cleanup_luminance(gray, params, ocr=True)
    return _apply_region(_gray(image), enhanced, params["region"])


def _diff_overlay(original: Image.Image, enhanced: Image.Image) -> Image.Image:
    base = original.convert("RGB")
    target = enhanced.convert("RGB")
    if target.size != base.size:
        target = target.resize(base.size)
    diff = ImageChops.difference(base, target).convert("L")
    diff = ImageEnhance.Contrast(diff).enhance(3.0)
    red = Image.new("RGB", base.size, (220, 38, 38))
    mask = diff.point(lambda v: min(170, v * 2))
    return Image.composite(red, base, mask)


def _edge_overlap(original: Image.Image, enhanced: Image.Image) -> float:
    a = _gray(original).copy()
    b = _gray(enhanced).copy()
    a.thumbnail((800, 1000))
    b = b.resize(a.size)
    ae = a.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 35 else 0).convert("1")
    be = b.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 35 else 0).convert("1")
    ah = ae.histogram()
    bh = be.histogram()
    both = ImageChops.logical_and(ae, be).histogram()
    union = ImageChops.logical_or(ae, be).histogram()
    intersection = both[255] if len(both) > 255 else 0
    union_count = union[255] if len(union) > 255 else 0
    if union_count <= 0:
        return 100.0
    return round(100.0 * intersection / union_count, 2)


def fidelity_report(original: Image.Image, enhanced: Image.Image, *, deskew_angle: float) -> dict:
    edge_overlap = _edge_overlap(original, enhanced)
    geometry_preserved = original.size == enhanced.size
    safe_transform = abs(deskew_angle) <= 2.0
    passed = geometry_preserved and safe_transform and edge_overlap >= 42.0
    return {
        "passed": passed,
        "geometry_preserved": geometry_preserved,
        "edge_overlap_percent": edge_overlap,
        "deskew_angle": round(deskew_angle, 2),
        "content_synthesis_used": False,
        "inpainting_used": False,
        "object_completion_used": False,
        "generative_redraw_used": False,
    }


def enhance_page(data: bytes, *, profile: str = "balanced", params: dict | None = None) -> EnhancementResult:
    image = _open_image(data)
    normalized = normalize_params(profile, params)
    metrics_before = quality_metrics(image)
    angle = estimate_deskew_angle(image) if normalized["deskew"] else 0.0
    visual = _visual_enhance(image, normalized, angle)
    ocr = _ocr_enhance(image, normalized, angle)
    metrics_after = quality_metrics(visual)
    fidelity = fidelity_report(image, visual, deskew_angle=angle)
    return EnhancementResult(
        visual_png=_png(visual),
        ocr_png=_png(ocr),
        diff_png=_png(_diff_overlay(image, visual)),
        metrics_before=metrics_before,
        metrics_after=metrics_after,
        fidelity=fidelity,
        profile=profile,
        params=normalized,
        suggested_profile=suggest_profile(metrics_before),
    )


def analyze_page(data: bytes) -> dict:
    image = _open_image(data)
    metrics = quality_metrics(image)
    return {
        "metrics": metrics,
        "suggested_profile": suggest_profile(metrics),
        "needs_cleanup": float(metrics.get("overall") or 0) < 78.0,
        "content_synthesis_used": False,
    }
