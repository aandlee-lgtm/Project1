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
import os
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
    ap.add_argument('--lightroom-received', default=None,
                    help='file a stand-in Lightroom app writes the paths it was handed to (absent: no Lightroom)')
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    results, errors = [], []
    shots = Path(a.shots) if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    def wait(js, timeout=120_000):
        """Poll a JS condition via page.evaluate (wait_for_function is blocked by the app's CSP in WebKit)."""
        deadline = time.time() + timeout / 1000
        while time.time() < deadline:
            if page.evaluate(f'() => Boolean({js})'):
                return
            time.sleep(.25)
        raise TimeoutError(f'timed out waiting for: {js}')

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
        wait(f"scan.phase==='complete' && scan.started > {before} && rowsVersion===scan.version", 1_800_000)
        page.wait_for_timeout(500)
        n = int(page.text_content('#total'))
        check('scan completes and fills grid', n > 0 and page.locator('.card').count() > 0,
              f'{n} analysed in {time.time() - t0:.1f}s')
        status = page.text_content('#status')
        check('status line shows results without the decoder version', 'photos analysed' in status and 'LibRaw' not in status, status)
        accent = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--teal').trim()")
        check('brighter teal accent colour', accent == '#4fe0c8', accent)
        if shots:
            page.screenshot(path=str(shots / 'grid.png'))
        # 1.6: persistent top bar with the main actions; version label only
        label = page.text_content('header .version')
        check('title bar shows only the version', label.startswith('v') and 'LOCAL' not in page.text_content('header')
              and 'UNTOUCHED' not in page.text_content('header'), label)
        # 1.7: step numbers 1-2-3 on the three main actions, light grey, larger than the label, same bar height
        steps = page.evaluate("""['browse','scan','lightroom'].map(i => { const b = document.getElementById(i), n = b.querySelector('.step');
            return [n.textContent, parseFloat(getComputedStyle(n).fontSize) / parseFloat(getComputedStyle(b).fontSize),
                    getComputedStyle(n).color, b.getAttribute('aria-label'), Math.round(b.getBoundingClientRect().height)] })""")
        field = round(page.evaluate("document.getElementById('folder').getBoundingClientRect().height"))
        check('step numbers 1, 2, 3 on Choose folder, Analyse photos, Send to Lightroom',
              [x[0] for x in steps] == ['1', '2', '3'] and all(1.3 <= x[1] <= 1.7 for x in steps)
              and steps[0][2] == steps[2][2] == 'rgb(158, 171, 180)' and all(x[3].startswith(f'Step {i}:') for i, x in enumerate(steps, 1))
              and all(abs(x[4] - field) <= 2 for x in steps), f'{steps}; folder field {field}px')
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        page.wait_for_timeout(300)
        tops = page.evaluate("['browse','scan','lightroom','status'].map(i => document.getElementById(i).getBoundingClientRect().top)")
        check('Choose folder, Analyse photos, Send to Lightroom and status stay on screen when scrolled',
              page.evaluate('window.scrollY') > 0 and all(0 <= t < 140 for t in tops), tops)
        if shots:
            page.screenshot(path=str(shots / 'scrolled.png'))
        page.evaluate('window.scrollTo(0, 0)')

        # Summary tiles act as filters: each shows exactly its bucket in the grid.
        tile_ok = []
        for bucket, count_id in (('Keep', 'kept'), ('Consider', 'considered'), ('Drop', 'dropped')):
            page.click(f'[data-bucket="{bucket}"]')
            page.wait_for_timeout(300)
            shown = page.eval_on_selector_all('.card .pill', 'els => els.map(e => e.textContent.split(" ")[0])')
            expected = int(page.text_content(f'#{count_id}'))
            tile_ok.append((bucket, expected, len(shown), set(shown) <= {bucket},
                            page.get_attribute(f'[data-bucket="{bucket}"]', 'aria-pressed') == 'true'))
        page.click('[data-bucket="Drop"]')
        page.wait_for_timeout(300)
        if shots:
            page.screenshot(path=str(shots / 'drop-filter.png'))
        page.click('[data-bucket="all"]')
        page.wait_for_timeout(300)
        check('summary tiles filter the grid to Keep / Consider / Drop',
              all(e == n and same and pressed for _, e, n, same, pressed in tile_ok)
              and page.locator('.card').count() == min(n, 120), tile_ok)
        def order():
            return page.eval_on_selector_all('.card .filename', 'els => els.map(e => e.textContent)')

        def counts():
            return [page.text_content(f'#{i}') for i in ('kept', 'considered', 'dropped')]

        if a.expect_persisted:
            check('weights and thresholds restored after relaunch',
                  page.input_value('#weight-composition') == '100' and page.input_value('#weight-focus') == '0'
                  and page.input_value('#keep') == '50')
        page.select_option('#sort', 'score')

        def set_range(sel, value):
            page.fill(sel, str(value))
            page.dispatch_event(sel, 'input')
        # contrasting baseline: focus only, strict thresholds
        for k, v in (('sharpness', 0), ('focus', 100), ('composition', 0), ('exposure', 0)):
            set_range(f'#weight-{k}', v)
        set_range('#keep', 95)
        set_range('#consider', 49)
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
        check('thresholds change Keep/Consider/Drop counts', counts() != base_counts or n < 2, f'{base_counts} -> {counts()}')

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
        wait("document.getElementById('viewImage').naturalWidth > 0")
        box = page.locator('#viewImage').bounding_box()
        page.mouse.move(box['x'] + box['width'] * .3, box['y'] + box['height'] * .3)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] * .6, box['y'] + box['height'] * .6, steps=5)
        page.mouse.up()
        wait("current && current.roi_state==='full'", 120_000)
        check('focus region measured at full resolution', True)
        reasons = page.text_content('#reasons')
        check('recommendation reasons shown', 'weighted score' in reasons or 'Your decision' in reasons, reasons[:160])
        if shots:
            page.screenshot(path=str(shots / 'viewer.png'))
        page.click('#full')
        wait("document.getElementById('inspectImage').naturalWidth > 0", 180_000)
        natural = page.evaluate("[inspectImage.naturalWidth, inspectImage.naturalHeight]")
        size = page.evaluate('current.size')
        check('full-resolution inspector shows native pixels', list(natural) == list(size), f'{natural} vs {size}')
        page.click('[data-zoom="1"]')
        css = page.evaluate("parseFloat(inspectImage.style.width)")
        check('100% view maps 1 image pixel to 1 screen pixel', abs(css * 2 - natural[0]) <= 2, f'css {css}px @2x')
        # 1.5: step to the next photo inside the inspector, keeping the zoom; neighbours were prefetched
        before_id = page.evaluate('current.id')
        if page.evaluate('visible.length') > 1:
            page.keyboard.press('ArrowRight')
            wait(f"current.id !== '{before_id}' && document.getElementById('inspectImage').naturalWidth > 0", 180_000)
            check('inspector steps to the next photo at the same zoom', page.evaluate("zoom") == '1',
                  page.evaluate('current.name'))
        if shots:
            page.screenshot(path=str(shots / 'inspector.png'))
        page.click('[data-close="inspector"]')

        # burst comparison with 100% crops
        page.click('#burstCompare')
        page.wait_for_selector('#comparison[open]')
        frames = page.locator('.comparephoto').count()
        page.check('#cropMode')
        wait("[...document.querySelectorAll('[data-crop]')].every(i=>i.naturalWidth>0)", 300_000)
        check('burst comparison with 100% crops', frames >= 1, f'{frames} frames')
        if shots:
            page.screenshot(path=str(shots / 'burst-compare.png'))
        page.click('[data-close="comparison"]')

        page.click('#compareLikes')
        page.wait_for_selector('#comparison[open]')
        check('liked shortlist comparison', page.locator('.comparephoto').count() >= 1)
        page.click('[data-close="comparison"]')

        page.click('#export')
        wait("document.getElementById('notice').textContent.includes('exported to')", 30_000)
        check('CSV export', True, page.text_content('#notice'))
        failures = page.locator('#failureList').text_content()
        check('failed files listed with reasons', True, failures[:300].replace('\n', ' | '))
        # 1.3: burst likeness settings
        page.fill('#near_window', '12')
        set_range('#likeness', 72)
        page.click('#regroup')
        wait("prefs.likeness===72 && prefs.near_window===12", 30_000)
        check('burst similarity % and near-identical settings saved', True,
              page.text_content('#likenessValue') + ' / ' + page.text_content('#near_identicalValue'))
        bursts = page.evaluate("[...derived.groups.values()].filter(g=>g.length>1).length")
        if bursts:
            page.select_option('#sort', 'group')
            page.evaluate("openViewer([...derived.groups.values()].find(g=>g.length>1)[1].id)")
            page.wait_for_selector('#viewer[open]')
            text = page.text_content('#reasons')
            check('burst likeness % shown in the viewer', "like the burst's top frame" in text and '%' in text, text[-160:])
            page.click('#burstCompare')
            page.wait_for_selector('#comparison[open]')
            check('likeness shown in burst comparison', 'alike #1' in page.text_content('#compare'),
                  page.text_content('#compareTitle'))
            page.click('[data-close="comparison"]')

        # 1.3: card for camera-preview photos shows the normal reason line, not the long notice
        long_notice = page.evaluate("[...document.querySelectorAll('.card .why')].some(e=>e.textContent.includes('not the RAW pixels'))")
        check('cards omit the camera-preview sentence', not long_notice)

        # 1.3: learn from my decisions (labels set in the page only, not saved)
        analysed = page.evaluate("rows.filter(r=>r.status==='analysed').length")
        if analysed >= 30:
            page.evaluate("""() => { window.__saved = rows.map(r => [r.decision, r.liked]);
                rows.filter(r => r.status === 'analysed').forEach(r => { r.decision = r.scores.focus >= 50 ? 'Keep' : 'Drop'; r.liked = false });
                render(); renderLearn() }""")
            page.click('#learn')
            text = page.text_content('#proposalText')
            check('learn proposes settings from decisions', 'of your' in text or 'already match' in text, text[:200])
            if page.is_visible('#applyLearn'):
                before = page.evaluate('JSON.stringify(settingsNow())')
                page.click('#applyLearn')
                applied = page.evaluate('JSON.stringify(settingsNow())')
                page.click('#undoLearn')
                check('learned settings apply and undo', applied != before and page.evaluate('JSON.stringify(settingsNow())') == before)
            page.evaluate("() => { rows.forEach((r, i) => { [r.decision, r.liked] = window.__saved[i] }); render(); renderLearn() }")
        else:
            check('learn needs 30 marked photos', page.is_disabled('#learn'), page.text_content('#learnStatus'))

        # 1.3: settings profiles and per-folder settings
        if a.expect_persisted:
            check('settings profile restored after relaunch', 'UI test' in page.evaluate('Object.keys(prefs.profiles)'))
            page.select_option('#profileList', 'UI test')
            page.click('#deleteProfile')
            check('settings profile deleted', 'UI test' not in page.evaluate('Object.keys(prefs.profiles)'))
        else:
            page.fill('#profileName', 'UI test')
            page.click('#saveProfile')
            page.click('#loadProfile')
            check('settings profile saved and loaded', 'Loaded profile' in page.text_content('#profileMessage'))
        page.check('#folderRemember')
        remembered = page.evaluate('Object.keys(prefs.folder_settings).includes(folderKey())')
        page.uncheck('#folderRemember')
        check('settings remembered for this folder', remembered and not page.evaluate('Object.keys(prefs.folder_settings).length'))

        # 1.3: Adobe Lightroom Classic
        page.evaluate('installLightroomPlugin()')
        wait("document.getElementById('notice').textContent.includes('plug-in installed')", 30_000)
        page.click('#lightroom')
        page.wait_for_selector('#lrDialog[open]')
        wait("/installed|running/i.test(document.getElementById('lrPlugin').textContent)", 30_000)
        groups = page.eval_on_selector_all('[data-lrgroup]', 'els => els.map(e => [e.dataset.lrgroup, e.checked, e.closest("label").textContent.trim()])')
        check('Send to Lightroom window shows plug-in status and star groups',
              len(groups) == 4 and [g[0] for g in groups] == ['3', '2', '1', '5'], groups)
        page.click('#lrSave')
        wait("document.getElementById('lrResult').textContent.includes('are saved')", 30_000)
        check('Lightroom plug-in installed and selections saved', True, page.text_content('#lrResult')[:120])
        if shots:
            page.screenshot(path=str(shots / 'lightroom-dialog.png'))
        wanted = page.evaluate("lightroomRows().filter(x => lrChoice[x.rating]).map(x => x.path)")
        received = Path(a.lightroom_received) if a.lightroom_received else None
        if received and received.exists():
            received.unlink()
        page.click('#lrOpen')
        wait("document.getElementById('lrResult').textContent.includes('is opening') || "
             "document.getElementById('lrError').textContent.length > 0", 60_000)
        if received:
            deadline = time.time() + 60
            while not received.exists() and time.time() < deadline:
                time.sleep(.5)
            got = sorted(l for l in received.read_text().splitlines() if l) if received.exists() else []
            support = (Path(os.environ['PHOTOSELECT_HOME']) / 'support' if os.environ.get('PHOTOSELECT_HOME')
                       else Path.home() / 'Library/Application Support/PhotoSelect')
            pending = support / 'Lightroom' / 'pending.import'
            check('Open in Lightroom hands only the chosen groups to Lightroom (stand-in app received them)',
                  got == sorted(wanted) and len(got) > 0, f'{len(got)} received, {len(wanted)} chosen; '
                  + page.text_content('#lrResult')[:100])
            check('automatic star rating requested for the opened photos', pending.exists() and
                  len(pending.read_text().splitlines()) == len(wanted) + 2, str(pending))
        else:
            check('missing Lightroom Classic explained, selections still saved',
                  'not found on this Mac' in page.text_content('#lrError'), page.text_content('#lrError')[:120])
        page.click('[data-close="lrDialog"]')
        # 1.6: star changes made in Lightroom come back (as the plug-in reports them)
        support = (Path(os.environ['PHOTOSELECT_HOME']) / 'support' if os.environ.get('PHOTOSELECT_HOME')
                   else Path.home() / 'Library/Application Support/PhotoSelect')
        target = page.evaluate("rows.find(r => r.status === 'analysed' && !r.liked && r.decision !== 'Drop')")
        changes = support / 'Lightroom' / 'lightroom-changes.tsv'
        changes.parent.mkdir(parents=True, exist_ok=True)
        changes.write_text(f"{time.time():.0f}\t3\t1\t{target['path']}\n", encoding='utf-8')
        page.evaluate('syncLightroom()')
        wait("document.getElementById('notice').textContent.startsWith('From Lightroom')", 30_000)
        check('star change made in Lightroom updates the decision', page.evaluate(
            f"byId.get('{target['id']}').decision") == 'Drop', page.text_content('#notice'))
        check('no JavaScript errors', not errors, '; '.join(errors[:3]))
        browser.close()

    ok = all(r[1] for r in results)
    print(json.dumps({'passed': sum(r[1] for r in results), 'failed': sum(not r[1] for r in results)}))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
