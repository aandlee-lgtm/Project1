"""Find the subject of a photo, so subject focus is measured where the subject is (1.11), and so a
crop can be suggested around it (1.12).

Uses macOS's built-in Vision framework (on-device; nothing leaves the Mac), trying in turn:
1. subject isolation (foreground instance mask, as in Photos' "lift subject from background",
   macOS 14 and later): the outline of the main subjects, such as a boat and its crew;
2. people detection (whole bodies): sailors;
3. objectness-based saliency: objects that stand out (1.11);
4. attention-based saliency: where the eye is drawn (1.11). When Vision is not available (not macOS, or it fails) no subject is found
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
MAX_AREA = 0.5        # an "object" covering more than half the frame is not a subject: use the central half

# What happened so far (shown in About and the diagnostic report, and checked by the macOS tests).
_stats_lock = threading.Lock()
stats = {'photos': 0, 'found': 0, 'by_isolation': 0, 'by_people': 0, 'by_objectness': 0, 'by_attention': 0,
         'too_large': 0, 'nothing': 0, 'errors': 0, 'cpu_only': 0, 'method_errors': 0, 'last_error': '',
         'last_method_error': ''}


def _count(key, error=None, field='last_error'):
    with _stats_lock:
        stats[key] += 1
        if error:
            stats[field] = str(error)[:300]


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
    if (x1 - x0) * (y1 - y0) > MAX_AREA:
        return None
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


_cpu_only = False   # set once Vision could not use the GPU / Neural Engine (e.g. a virtual Mac)


def _perform(handler, request):
    """Run one Vision request, retrying on the CPU when no inference context is available."""
    global _cpu_only
    if _cpu_only and hasattr(request, 'setUsesCPUOnly_'):
        request.setUsesCPUOnly_(True)
    ok, error = handler.performRequests_error_([request], None)
    if not ok and not _cpu_only and 'inference context' in str(error) and hasattr(request, 'setUsesCPUOnly_'):
        _cpu_only = True
        _count('cpu_only')
        request.setUsesCPUOnly_(True)
        ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f'{request.__class__.__name__}: {error}')
    return request.results() or []


def _top_left(bb, confidence):
    """Vision box (normalised, origin bottom-left) as (x, y, w, h, confidence), origin top-left."""
    return (bb.origin.x, 1 - bb.origin.y - bb.size.height, bb.size.width, bb.size.height, float(confidence))


def mask_box(mask):
    """Bounding box (x, y, w, h, 1.0) of the non-zero pixels of a 2-D label mask (numpy), or None."""
    import numpy as np
    rows, cols = np.nonzero(np.asarray(mask).any(axis=1)), np.nonzero(np.asarray(mask).any(axis=0))
    if not len(rows[0]):
        return None
    h, w = mask.shape
    y0, y1, x0, x1 = rows[0][0], rows[0][-1] + 1, cols[0][0], cols[0][-1] + 1
    return (x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h, 1.0)


def _isolation_boxes(Vision, handler):
    cls = getattr(Vision, 'VNGenerateForegroundInstanceMaskRequest', None)
    if cls is None:          # before macOS 14
        return []
    import numpy as np
    import Quartz
    out = []
    for observation in _perform(handler, cls.alloc().init()):
        buffer = observation.instanceMask()      # one byte per pixel: 0 background, 1..n subjects
        Quartz.CVPixelBufferLockBaseAddress(buffer, 1)
        try:
            w, h = Quartz.CVPixelBufferGetWidth(buffer), Quartz.CVPixelBufferGetHeight(buffer)
            row = Quartz.CVPixelBufferGetBytesPerRow(buffer)
            raw = Quartz.CVPixelBufferGetBaseAddress(buffer).as_buffer(row * h)
            mask = np.frombuffer(raw, dtype=np.uint8).reshape(h, row)[:, :w].copy()
        finally:
            Quartz.CVPixelBufferUnlockBaseAddress(buffer, 1)
        box = mask_box(mask)
        if box:
            out.append(box)
    return out


def _people_boxes(Vision, handler):
    request = Vision.VNDetectHumanRectanglesRequest.alloc().init()
    if hasattr(request, 'setUpperBodyOnly_'):
        request.setUpperBodyOnly_(False)
    return [_top_left(o.boundingBox(), o.confidence()) for o in _perform(handler, request)]


def _saliency_boxes(Vision, handler, cls):
    return [_top_left(item.boundingBox(), item.confidence())
            for observation in _perform(handler, cls.alloc().init()) for item in observation.salientObjects() or []]


def find_subject(preview):
    """(x, y, w, h) around the subject of a PIL image, or None when none is found (methods: see top)."""
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
            methods = (('by_isolation', lambda h: _isolation_boxes(Vision, h)),
                       ('by_people', lambda h: _people_boxes(Vision, h)),
                       ('by_objectness', lambda h: _saliency_boxes(Vision, h, Vision.VNGenerateObjectnessBasedSaliencyImageRequest)),
                       ('by_attention', lambda h: _saliency_boxes(Vision, h, Vision.VNGenerateAttentionBasedSaliencyImageRequest)))
            errors, any_boxes = [], False
            for key, method in methods:
                handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, {})
                try:
                    boxes = method(handler)
                except Exception as error:
                    errors.append(error)
                    _count('method_errors', f'{key}: {error}', 'last_method_error')
                    continue
                any_boxes = any_boxes or bool(boxes)
                found = choose(boxes)
                if found:
                    _count('found')
                    _count(key)
                    return found
            if len(errors) == len(methods):
                _count('errors', errors[-1])
                log.info('Vision subject finding failed: %s', errors[-1])
            elif any_boxes:
                _count('too_large')
            else:
                _count('nothing')
            return None
    except Exception as error:
        _count('errors', error)
        log.exception('automatic subject finding failed')
        return None
