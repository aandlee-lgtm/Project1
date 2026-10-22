"""Find the subject of a photo, so subject focus is measured where the subject is (1.11).

Uses macOS's built-in Vision framework (on-device; nothing leaves the Mac): the objectness-based
saliency request returns boxes around the objects that stand out, such as a boat on water or a
person against the sky. When Vision is not available (not macOS, or it fails) no subject is found
and focus is measured in the central half of the frame, as before 1.11.

Boxes are (x, y, w, h) fractions of the frame, origin top-left, like a region you draw yourself.
"""
import io
import logging
import threading

log = logging.getLogger('photoselect.subject')

PAD = 0.10           # grow the found box by 10 % of its size on every side
MIN_SIDE = 0.12      # never measure in an area narrower or lower than 12 % of the frame
MIN_CONFIDENCE = 0.0  # Vision only returns objects it finds salient; their confidence is often low

# What happened so far (shown in About and the diagnostic report, and checked by the macOS tests).
_stats_lock = threading.Lock()
stats = {'photos': 0, 'found': 0, 'by_objectness': 0, 'by_attention': 0, 'nothing': 0, 'errors': 0, 'last_error': ''}


def _count(key, error=None):
    with _stats_lock:
        stats[key] += 1
        if error:
            stats['last_error'] = str(error)[:300]


def stats_snapshot():
    with _stats_lock:
        return dict(stats)

_vision = None       # (Vision, Foundation, objc) once imported; False when unavailable


def _modules():
    global _vision
    if _vision is None:
        try:
            import objc
            import Foundation
            import Vision
            _vision = (Vision, Foundation, objc)
        except Exception as error:   # not macOS, or the framework bindings are missing
            log.info('automatic subject finding unavailable: %s', error)
            _vision = False
    return _vision or None


def available():
    return _modules() is not None


def finder_name():
    return 'macOS Vision' if available() else 'unavailable'


def choose(boxes):
    """The area to measure from Vision's boxes [(x, y, w, h, confidence)], or None.

    Keeps the boxes at least half as confident as the best one (several boats or sailors become one
    area around them all), then pads the area and gives it a minimum size, inside the frame."""
    boxes = [b for b in boxes if b[4] >= MIN_CONFIDENCE and b[2] > 0 and b[3] > 0]
    if not boxes:
        return None
    best = max(b[4] for b in boxes)
    keep = [b for b in boxes if b[4] >= best / 2] if best > 0 else boxes
    x0 = min(b[0] for b in keep)
    y0 = min(b[1] for b in keep)
    x1 = max(b[0] + b[2] for b in keep)
    y1 = max(b[1] + b[3] for b in keep)
    return region_around(x0, y0, x1, y1)


def region_around(x0, y0, x1, y1):
    """Pad (x0, y0)-(x1, y1), enforce MIN_SIDE and keep it inside the frame; (x, y, w, h)."""
    w, h = x1 - x0, y1 - y0
    x0, x1 = x0 - w * PAD, x1 + w * PAD
    y0, y1 = y0 - h * PAD, y1 + h * PAD

    def span(a, b):
        if b - a < MIN_SIDE:
            c = (a + b) / 2
            a, b = c - MIN_SIDE / 2, c + MIN_SIDE / 2
        a, b = max(0.0, a), min(1.0, b)
        if b - a < MIN_SIDE:     # pushed against an edge: extend inwards
            a, b = (0.0, MIN_SIDE) if a == 0.0 else (1.0 - MIN_SIDE, 1.0)
        return a, b

    x0, x1 = span(x0, x1)
    y0, y1 = span(y0, y1)
    return tuple(round(v, 4) for v in (x0, y0, x1 - x0, y1 - y0))


def _salient_boxes(Vision, handler, request):
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f'{request.__class__.__name__}: {error}')
    boxes = []
    for observation in request.results() or []:
        for item in observation.salientObjects() or []:
            bb = item.boundingBox()   # normalised, origin bottom-left
            boxes.append((bb.origin.x, 1 - bb.origin.y - bb.size.height, bb.size.width,
                          bb.size.height, float(item.confidence())))
    return boxes


def find_subject(preview):
    """(x, y, w, h) around the subject of a PIL image, or None when none is found.

    Tries Vision's objectness-based saliency (objects that stand out), then its attention-based
    saliency (where the eye is drawn) when the first finds nothing."""
    mods = _modules()
    if mods is None:
        return None
    Vision, Foundation, objc = mods
    _count('photos')
    try:
        with objc.autorelease_pool():
            buf = io.BytesIO()
            preview.convert('RGB').save(buf, 'JPEG', quality=85)
            raw = buf.getvalue()
            data = Foundation.NSData.dataWithBytes_length_(raw, len(raw))
            errors = []
            for key, cls in (('by_objectness', Vision.VNGenerateObjectnessBasedSaliencyImageRequest),
                             ('by_attention', Vision.VNGenerateAttentionBasedSaliencyImageRequest)):
                handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, {})
                try:
                    found = choose(_salient_boxes(Vision, handler, cls.alloc().init()))
                except Exception as error:
                    errors.append(error)
                    continue
                if found:
                    _count('found')
                    _count(key)
                    return found
            if errors:
                _count('errors', errors[-1])
                log.info('Vision saliency failed: %s', errors[-1])
            else:
                _count('nothing')
            return None
    except Exception as error:
        _count('errors', error)
        log.exception('automatic subject finding failed')
        return None
