"""Transparent image-quality heuristics and burst grouping.

None of these measures is a trained model. They are relative cues:

* sharpness   – Laplacian detail of the whole frame at 1,600 px, normalised by contrast.
* focus       – the same kind of detail measured in the subject region (default: central
                half) on a crop taken from the full-resolution decode, resampled to a common
                4,000 px-long-edge scale so mixed cameras are comparable (smaller frames
                at native size). A light low-pass
                filter is applied first and the detail expected from the estimated sensor
                noise is subtracted, so grain counts for less. Real texture (waves, foliage,
                a sharp background) is still counted as detail.
* composition – edge-energy centroid near rule-of-thirds points, minus border clutter.
* exposure    – share of pixels that are not clipped to near-black or near-white.
* noise       – Immerkaer's fast noise estimate. Reported so that a high detail score that
                may be caused by noise, water or foliage texture can be flagged.
"""
import numpy as np
from PIL import Image

ANALYSIS_VERSION = 2
PREVIEW_EDGE = 1600
FOCUS_SCALE = 4000
DEFAULT_REGION = (0.25, 0.25, 0.5, 0.5)


def _gray(image):
    rgb = np.asarray(image.convert('RGB'), dtype=np.float32) / 255
    return rgb, rgb @ np.array([.299, .587, .114], dtype=np.float32)


def _detail(g):
    if min(g.shape) < 8:
        return 0.0
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    # Local contrast normalisation limits exposure dependence; noise and texture still count.
    return float(np.var(lap) / (np.var(g) + .01))


def _lowpass(g):
    """Separable [1 4 6 4 1]/16 binomial filter (sigma ~1 px) to damp per-pixel noise."""
    k = np.array([1, 4, 6, 4, 1], dtype=np.float32) / 16
    if min(g.shape) < 8:
        return g
    g = np.pad(g, 2, mode='reflect')
    g = sum(k[i] * g[:, i:i + g.shape[1] - 4] for i in range(5))
    return sum(k[i] * g[i:i + g.shape[0] - 4, :] for i in range(5))


def noise_sigma(gray):
    """Immerkaer (1996) fast noise standard deviation estimate, in 0-255 units."""
    h, w = gray.shape
    if h < 3 or w < 3:
        return 0.0
    g = gray * 255
    conv = (g[:-2, :-2] - 2 * g[:-2, 1:-1] + g[:-2, 2:] - 2 * g[1:-1, :-2] + 4 * g[1:-1, 1:-1]
            - 2 * g[1:-1, 2:] + g[2:, :-2] - 2 * g[2:, 1:-1] + g[2:, 2:])
    return float(np.sqrt(np.pi / 2) * np.abs(conv).sum() / (6 * (w - 2) * (h - 2)))


def valid_region(box):
    return (box is not None and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)
            and all(0 <= v <= 1 for v in box) and box[2] >= .02 and box[3] >= .02
            and box[0] + box[2] <= 1.001 and box[1] + box[3] <= 1.001)


def focus_detail(full, region=None):
    """Detail in a subject region, measured on the full-resolution image.

    The crop is resampled so the whole frame would be FOCUS_SCALE px on its long edge,
    keeping scores comparable between cameras with different sensor resolutions. Frames
    smaller than that are measured at native size (enlarging would correlate the noise and
    defeat the noise correction), so very small images are not directly comparable.
    """
    x, y, w, h = region or DEFAULT_REGION
    W, H = full.size
    box = (int(x * W), int(y * H), max(int((x + w) * W), int(x * W) + 8), max(int((y + h) * H), int(y * H) + 8))
    crop = full.crop(box)
    scale = FOCUS_SCALE / max(W, H)
    if scale < .99:
        crop = crop.resize((max(8, round(crop.width * scale)), max(8, round(crop.height * scale))),
                           Image.Resampling.BOX)
    _, g = _gray(crop)
    return round(_denoised_detail(g), 6)


def _kernel_gain():
    """Variance gain of white noise through the low-pass + Laplacian used for focus."""
    b = np.outer([1, 4, 6, 4, 1], [1, 4, 6, 4, 1]) / 256.0
    lap = np.array([[0, -1, 0], [-1, 4, -1], [0, -1, 0]], dtype=float)
    k = np.zeros((7, 7))
    for i in range(3):
        for j in range(3):
            k[i:i + 5, j:j + 5] += lap[i, j] * b
    return float((k ** 2).sum())


_NOISE_GAIN = _kernel_gain()


def _denoised_detail(g):
    """Low-passed Laplacian detail minus the part explained by estimated sensor noise."""
    if min(g.shape) < 8:
        return 0.0
    lp = _lowpass(g)
    lap = 4 * lp[1:-1, 1:-1] - lp[:-2, 1:-1] - lp[2:, 1:-1] - lp[1:-1, :-2] - lp[1:-1, 2:]
    sigma = noise_sigma(g) / 255
    return float(max(0.0, np.var(lap) - _NOISE_GAIN * sigma ** 2) / (np.var(g) + .01))


def preview_of(full):
    preview = full.copy()
    preview.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), Image.Resampling.LANCZOS, reducing_gap=3.0)
    return preview


def frame_metrics(preview):
    """Whole-frame metrics measured on the <=1,600 px analysis preview."""
    rgb, gray = _gray(preview)
    h, w = gray.shape
    gy, gx = np.gradient(gray)
    energy = np.hypot(gx, gy)
    total = float(energy.sum()) + 1e-8
    yy, xx = np.mgrid[0:h, 0:w]
    cx = float((energy * xx).sum() / total) / w
    cy = float((energy * yy).sum() / total) / h
    distance = min(np.hypot(cx - a, cy - b) for a in (1 / 3, 2 / 3) for b in (1 / 3, 2 / 3))
    bh, bw = max(1, h // 20), max(1, w // 20)
    framing = float(energy[:bh].sum() + energy[-bh:].sum() + energy[:, :bw].sum() + energy[:, -bw:].sum()) / total
    composition = float(np.clip(100 - distance * 130 - framing * 60, 0, 100))
    low = float((gray < .015).mean())
    high = float((gray > .985).mean())
    small = np.asarray(preview.resize((9, 8)).convert('L'))
    return {
        'sharpness': round(_detail(gray), 6),
        'composition': round(composition, 1),
        'exposure': round(100 * (1 - low - high), 1),
        'clip_low': round(100 * low, 2),
        'clip_high': round(100 * high, 2),
        'noise': round(noise_sigma(gray), 3),
        'hash': (small[:, 1:] > small[:, :-1]).flatten().astype(int).tolist(),
        'colour': [round(float(v), 4) for v in rgb.mean(axis=(0, 1))],
        'centre': [round(cx, 4), round(cy, 4)],
    }


def analyse(full, region=None):
    """Return (preview image, metrics) for a fully decoded image."""
    preview = preview_of(full)
    m = frame_metrics(preview)
    m['focus'] = focus_detail(full, region)
    m['focus_default'] = m['focus'] if region is None else focus_detail(full)
    return preview, m


def metrics(image, roi=None):
    """Compatibility helper: every metric from a single image (used by tests)."""
    _, m = analyse(image, roi)
    return m


def normalise(rows):
    """Map sharpness and focus onto 0-100 relative to this folder's 10th-90th percentiles.

    Rows must have 'raw' metrics. Scores are folder-relative rankings, not probabilities.
    """
    for key in ('sharpness', 'focus'):
        values = [r['raw'][key] for r in rows]
        if not values:
            continue
        lo, hi = np.percentile(values, [10, 90])
        for r in rows:
            v = r['raw'][key]
            r['scores'][key] = round(float(np.clip(50 if hi - lo < 1e-8 else 15 + 80 * (v - lo) / (hi - lo), 0, 100)), 1)
    noise = [r['raw'].get('noise', 0) for r in rows]
    high_noise = float(np.percentile(noise, 80)) if len(noise) >= 5 else float('inf')
    for r in rows:
        for key in ('composition', 'exposure'):
            r['scores'][key] = r['raw'][key]
        r['noise_flag'] = bool(r['raw'].get('noise', 0) >= high_noise and r['raw'].get('noise', 0) > 2.0)


def group_bursts(rows, gap=2, similarity=14):
    """Group frames shot within `gap` seconds that also look alike (hash + mean colour).

    Frames without a capture time stay in their own group.
    """
    ordered = sorted(rows, key=lambda r: (r['timestamp'] if r['timestamp'] is not None else float('inf'), r['name']))
    group = 0
    previous = anchor = None
    for row in ordered:
        similar = False
        if previous and row['timestamp'] is not None and previous['timestamp'] is not None:
            dt = row['timestamp'] - previous['timestamp']
            distance = sum(a != b for a, b in zip(row['raw']['hash'], anchor['raw']['hash']))
            colour = np.linalg.norm(np.array(row['raw']['colour']) - anchor['raw']['colour'])
            similar = 0 <= dt <= gap and distance <= similarity and colour < .18
        if not similar:
            group += 1
            anchor = row
        row['group'] = group
        previous = row
    return rows
