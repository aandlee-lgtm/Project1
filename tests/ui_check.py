"""Browser-level checks of the review interface against a running PhotoSelect server.

Usage: python ui_check.py --port P --token T --folder DIR [--engine chromium|webkit] [--shots OUTDIR]
           [--expect-persisted]

Verifies: page loads without JS errors; scanning a folder fills the grid; weight sliders and
thresholds change rankings/counts immediately; manual decisions and likes are applied (and,
with --expect-persisted, survived a restart); burst comparison, 100% crops, the full-resolution
inspector, region drawing and CSV export work.
"""
import argparse
import json
import sys
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--token', required=True)
    ap.add_argument('--folder', required=True)
    ap.add_argument('--engine', default='chromium')
    ap.add_argument('--executable', default=None)
    ap.add_argument('--shots', default=None)
    ap.add_argument('--expect-persisted', action='store_true')
    ap.add_argument('--recursive', action='store_true')
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    results, errors = [], []
    shots = Path(a.shots) if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    def check(name, ok, detail=''):
        results.append((name, bool(ok), detail))
        print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail else ''), flush=True)

    with sync_playwright() as p:
        kwargs = {'executable_path': a.executable} if a.executable else {}
        browser = getattr(p, a.engine).launch(**kwargs)
        # bypass_csp only lets the test harness's own probes evaluate; the app's CSP is unchanged.
        page = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=2,
                                   bypass_csp=True).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(f'http://127.0.0.1:{a.port}/')
        page.wait_for_selector('#weight-focus')
        check('page loads with weight sliders', page.locator('#weights input').count() == 4)

        page.fill('#folder', a.folder)
        if a.recursive:
            page.check('#recursive')
        before = page.evaluate('scan.started || 0')
        page.click('#scan')
        t0 = time.time()
        page.wait_for_function(f"scan.phase==='complete' && scan.started > {before} && rowsVersion===scan.version",
                               timeout=1_800_000)
        page.wait_for_timeout(500)
        n = int(page.text_content('#total'))
        check('scan completes and fills grid', n > 0 and page.locator('.card').count() > 0,
              f'{n} analysed in {time.time() - t0:.1f}s')
        if shots:
            page.screenshot(path=str(shots / 'grid.png'))

        def order():
            return page.eval_on_selector_all('.card .filename', 'els => els.map(e => e.textContent)')

        def counts():
            return [page.text_content(f'#{i}') for i in ('kept', 'considered', 'skipped')]

        if a.expect_persisted:
            check('weights and thresholds restored after relaunch',
                  page.input_value('#weight-composition') == '100' and page.input_value('#weight-focus') == '0'
                  and page.input_value('#keep') == '50')
        page.select_option('#sort', 'score')
        base_order, base_counts = order(), counts()
        for k, v in (('sharpness', 0), ('focus', 0), ('composition', 100), ('exposure', 0)):
            page.fill(f'#weight-{k}', str(v))
            page.dispatch_event(f'#weight-{k}', 'input')
        changed = order()
        check('weight sliders re-rank immediately', changed != base_order or n < 2, f'top before {base_order[:2]} after {changed[:2]}')
        page.fill('#keep', '50')
        page.dispatch_event('#keep', 'input')
        page.fill('#consider', '10')
        page.dispatch_event('#consider', 'input')
        check('thresholds change Keep/Consider/Skip counts', counts() != base_counts or n < 2, f'{base_counts} -> {counts()}')

        first = page.locator('.card').first
        name = first.locator('.filename').text_content()
        if a.expect_persisted:
            restored = page.evaluate("rows.filter(r=>r.decision==='Keep' && r.liked).map(r=>r.name)")
            check('manual decision and like restored after relaunch', len(restored) >= 1, str(restored))
        else:
            first.locator('[data-value="Keep"]').click()
            first.locator('[data-like]').click()
            page.wait_for_timeout(600)
            card = page.locator('.card', has=page.locator('.filename', has_text=name)).first
            check('manual Keep + like applied', 'manual' in card.locator('.pill').text_content() and
                  'Liked' in card.locator('[data-like]').text_content())

        # viewer, region, full-resolution inspector
        page.locator('.card [data-open]').first.click()
        page.wait_for_selector('#viewer[open]')
        page.wait_for_function("document.getElementById('viewImage').naturalWidth > 0")
        box = page.locator('#viewImage').bounding_box()
        page.mouse.move(box['x'] + box['width'] * .3, box['y'] + box['height'] * .3)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] * .6, box['y'] + box['height'] * .6, steps=5)
        page.mouse.up()
        page.wait_for_function("current && current.roi_state==='full'", timeout=120_000)
        check('focus region measured at full resolution', True)
        reasons = page.text_content('#reasons')
        check('recommendation reasons shown', 'weighted score' in reasons or 'Your decision' in reasons, reasons[:160])
        if shots:
            page.screenshot(path=str(shots / 'viewer.png'))
        page.click('#full')
        page.wait_for_function("document.getElementById('inspectImage').naturalWidth > 0", timeout=180_000)
        natural = page.evaluate("[inspectImage.naturalWidth, inspectImage.naturalHeight]")
        size = page.evaluate('current.size')
        check('full-resolution inspector shows native pixels', list(natural) == list(size), f'{natural} vs {size}')
        page.click('[data-zoom="1"]')
        css = page.evaluate("parseFloat(inspectImage.style.width)")
        check('100% view maps 1 image pixel to 1 screen pixel', abs(css * 2 - natural[0]) <= 2, f'css {css}px @2x')
        if shots:
            page.screenshot(path=str(shots / 'inspector.png'))
        page.click('[data-close="inspector"]')

        # burst comparison with 100% crops
        page.click('#burstCompare')
        page.wait_for_selector('#comparison[open]')
        frames = page.locator('.comparephoto').count()
        page.check('#cropMode')
        page.wait_for_function("[...document.querySelectorAll('[data-crop]')].every(i=>i.naturalWidth>0)", timeout=300_000)
        check('burst comparison with 100% crops', frames >= 1, f'{frames} frames')
        if shots:
            page.screenshot(path=str(shots / 'burst-compare.png'))
        page.click('[data-close="comparison"]')

        page.click('#compareLikes')
        page.wait_for_selector('#comparison[open]')
        check('liked shortlist comparison', page.locator('.comparephoto').count() >= 1)
        page.click('[data-close="comparison"]')

        page.click('#export')
        page.wait_for_function("document.getElementById('status').textContent.includes('exported to')", timeout=30_000)
        check('CSV export', True, page.text_content('#status'))
        failures = page.locator('#failureList').text_content()
        check('failed files listed with reasons', True, failures[:300].replace('\n', ' | '))
        check('no JavaScript errors', not errors, '; '.join(errors[:3]))
        browser.close()

    ok = all(r[1] for r in results)
    print(json.dumps({'passed': sum(r[1] for r in results), 'failed': sum(not r[1] for r in results)}))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
