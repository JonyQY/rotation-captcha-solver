"""Opt-in, single-attempt Baidu diagnostic in a fresh, independent Edge session.

No user browser profile, cookies, HAR, request payloads or verification tokens
are imported or exported. stdin commands keep preparation separate from a test.
"""
import argparse
import base64
from contextlib import nullcontext
import json
import math
from pathlib import Path
import sys
from time import perf_counter
from urllib.parse import urlsplit

from .api import AngleSession, offset_for
from .diagnostic_control import consume_one, control_lock, write_json

TARGET = 'https://ziyuan.baidu.com/linksubmit/url'
PUBLIC_LINK = 'https://www.baidu.com/'


def numeric_verdict(payload):
    """Retain only numeric result codes, never ds/tk/as or other body fields."""
    if not isinstance(payload, dict):
        return {}
    result = {k: v for k in ('code', 'status')
              if isinstance(v := payload.get(k), int) and not isinstance(v, bool)}
    data = payload.get('data')
    if isinstance(data, dict):
        result.update({k: v for k in ('op', 'opp')
                       if isinstance(v := data.get(k), int) and not isinstance(v, bool)})
    return result


def rotation_degrees(matrix):
    if matrix == 'none':
        return 0.0
    if matrix and matrix.startswith('matrix('):
        values = [float(v) for v in matrix[7:-1].split(',')]
        return round(math.degrees(math.atan2(values[1], values[0])) % 360, 2)
    return None


def classify(samples, responses):
    for response in reversed(responses):
        if response.get('path') == '/linksubmit/urlsubmit':
            status = response.get('status_code')
            if status == 0:
                return 'business_success'
            if status == 101:
                return 'business_verification_rejected'
    if any('验证通过' in sample.get('visible', []) for sample in samples):
        return 'widget_success_business_unconfirmed'
    if any('图片未转正' in sample.get('visible', []) for sample in samples):
        return 'widget_reported_image_not_upright'
    if any(response.get('op') == 3 for response in responses):
        return 'captcha_rejected'
    if any(sample.get('image_changed') for sample in samples):
        return 'challenge_replaced_reason_unknown'
    return 'no_conclusive_verdict'


SNAPSHOT = """original => {
    const img = document.querySelector('img.passMod_spin-background');
    const btn = document.querySelector('.passMod_slide-btn');
    const visible = Array.from(document.querySelectorAll(
        '.passMod_verify-success,.passMod_verify-fail,.passMod_verify-network,.passMod_verify-pending'
    )).filter(e => {const s=getComputedStyle(e); return e.getClientRects().length &&
        s.display!=='none' && s.visibility!=='hidden' && Number(s.opacity)>0;
    }).map(e => e.textContent.trim());
    return {image_changed: !img || img.currentSrc !== original,
        image_transform: img ? getComputedStyle(img).transform : null,
        handle_transform: btn ? getComputedStyle(btn).transform : null,
        visible, message: document.querySelector('.passMod_spin-msg')?.textContent || '',
        business_title: document.querySelector('#dialog-title')?.textContent || ''};
}"""


def is_target(url):
    actual, target = urlsplit(url), urlsplit(TARGET)
    return (actual.scheme, actual.netloc, actual.path) == (
        target.scheme, target.netloc, target.path)


def page_status(page):
    parts = urlsplit(page.url)
    return {'type': 'status', 'at_target': is_target(page.url),
            'logged_in': page.locator('a[href*="/auth/logout"]').is_visible(),
            'origin': f'{parts.scheme}://{parts.netloc}', 'path': parts.path}


def choose_page(context, current):
    """Login may finish in another tab; keep all user-created tabs intact."""
    pages = [p for p in context.pages if not p.is_closed()]
    for candidate in reversed(pages):
        if is_target(candidate.url) and candidate.locator('a[href*="/auth/logout"]').is_visible():
            return candidate
    if not current.is_closed():
        return current
    if pages:
        return pages[-1]
    raise RuntimeError('Test browser was closed')


def run_attempt(page, model, output):
    if not is_target(page.url) or not page.locator('a[href*="/auth/logout"]').is_visible():
        raise RuntimeError('Log in manually in this independent browser and return to the test page.')
    output.mkdir(parents=True, exist_ok=True)
    responses, samples = [], []
    started = perf_counter()

    def record(request):
        parts = urlsplit(request.url)
        if request.resource_type not in ('xhr', 'fetch') or not (
                parts.hostname == 'baidu.com' or (parts.hostname or '').endswith('.baidu.com')):
            return
        response = request.response()
        if response is None:
            return
        entry = {'elapsed_ms': round((perf_counter() - started) * 1000, 2),
                 'host': parts.hostname, 'path': parts.path, 'http_status': response.status}
        try:
            codes = numeric_verdict(response.json())
            entry.update({('status_code' if k == 'status' else k): v for k, v in codes.items()})
        except Exception:
            pass
        responses.append(entry)

    page.on('requestfinished', record)
    report = {'result': 'incomplete', 'public_link': PUBLIC_LINK}
    try:
        img = page.locator('img.passMod_spin-background')
        if img.is_visible():
            previous = img.get_attribute('src')
            page.locator('.passMod_dialog-footer-refresh').click()
            page.wait_for_function("old => document.querySelector('img.passMod_spin-background')?.src !== old", arg=previous)
        else:
            page.locator('#url').fill(PUBLIC_LINK)
            page.locator('#saveBtn').click()
        img.wait_for(state='visible', timeout=15000)
        page.wait_for_function("() => {const i=document.querySelector('img.passMod_spin-background'); return i?.complete && i.naturalWidth>0;}")
        source = img.get_attribute('src')
        captured_at = perf_counter()
        fetched = page.evaluate("""async src => {
            const response = await fetch(src, {credentials:'include', signal:AbortSignal.timeout(5000)});
            if (!response.ok) throw new Error('image_http_' + response.status);
            const bytes = new Uint8Array(await response.arrayBuffer());
            let raw=''; for (let i=0;i<bytes.length;i+=0x8000)
                raw+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
            return btoa(raw);
        }""", source)
        image = output / 'puzzle.jpg'
        image.write_bytes(base64.b64decode(fetched))
        inference_started = perf_counter()
        angle = model.read_angle(image)
        report.update(angle_cw=angle, inference_ms=round((perf_counter()-inference_started)*1000, 2))
        if angle is None:
            report['result'] = 'no_consensus'
            return report
        handle = page.locator('.passMod_slide-btn').bounding_box()
        rail = page.locator('.passMod_slide-control').bounding_box()
        if not handle or not rail:
            raise RuntimeError('Slider geometry unavailable')
        # This SDK maps one turn to width-52; do not infer it from the visible handle alone.
        span = rail['width'] - 52
        if span <= 0:
            raise RuntimeError('Invalid slider width')
        distance = offset_for(angle, span, complement=True)
        report.update(offset_px=distance, pixels_per_turn=span)
        if img.get_attribute('src') != source:
            report['result'] = 'image_changed_before_drag'
            return report
        age = perf_counter() - captured_at
        if age > 10:
            report['result'] = 'preparation_too_slow'
            return report

        def sample():
            value = page.evaluate(SNAPSHOT, source)
            value.update(elapsed_ms=round((perf_counter()-started)*1000, 2),
                         rotation_deg=rotation_degrees(value['image_transform']))
            if not samples or {k:v for k,v in value.items() if k!='elapsed_ms'} != {
                    k:v for k,v in samples[-1].items() if k!='elapsed_ms'}:
                samples.append(value)

        sample()
        x, y = handle['x']+handle['width']/2, handle['y']+handle['height']/2
        page.mouse.move(x, y)
        report['capture_to_drag_ms'] = round((perf_counter()-captured_at)*1000, 2)
        page.mouse.down()
        try:
            for step in range(1, 13):
                page.mouse.move(x+distance*step/12, y)
                page.wait_for_timeout(20)
            sample()
        finally:
            page.mouse.up()
        for _ in range(100):
            page.wait_for_timeout(50)
            sample()
        report['result'] = classify(samples, responses)
        page.screenshot(path=str(output/'result.png'))
        return report
    except Exception as error:
        # Do not persist raw browser exception messages containing URLs with tokens.
        report.update(result='diagnostic_error', error_type=type(error).__name__)
        return report
    finally:
        page.remove_listener('requestfinished', record)
        report.update(samples=samples, responses=responses,
                      elapsed_ms=round((perf_counter()-started)*1000, 2))
        (output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def run_browser(args):
    """Keep the browser owned by this process, not by an interactive terminal."""
    from playwright.sync_api import sync_playwright
    model = AngleSession()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = None
        if args.keep_login:
            # This is a dedicated profile created here, never the user's Edge profile.
            context = playwright.chromium.launch_persistent_context(
                str(output/'browser-profile'), channel='msedge', headless=False)
        else:
            browser = playwright.chromium.launch(channel='msedge', headless=False)
            context = browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(15000)
        page.goto(TARGET)
        page.screenshot(path=str(output/'ready.png'))
        ready = {'type':'ready', 'manual_login_if_required':True,
                 'keep_login':args.keep_login}
        print(json.dumps(ready), flush=True)
        if args.control_dir:
            write_json(args.control_dir/'ready.json', ready)
        attempted = False
        stopping = False

        def handle(request):
            nonlocal page, attempted, stopping
            action = request.get('action')
            page = choose_page(context, page)
            if action == 'status':
                return page_status(page)
            if action == 'prepare':
                page.goto(TARGET)
                page.screenshot(path=str(output/'ready.png'))
                result = page_status(page)
                result['screenshot'] = str(output/'ready.png')
                return result
            if action == 'test_once' and request.get('confirmed') is True:
                if attempted and not args.control_dir:
                    raise ValueError('This process permits one test only')
                if not is_target(page.url) or not page.locator('a[href*="/auth/logout"]').is_visible():
                    raise ValueError('Manual login required before testing')
                attempted = True
                return run_attempt(page, model, output)
            if action == 'stop':
                stopping = True
                return {'type':'stopped'}
            raise ValueError('Expected status, prepare, test_once with confirmed:true, or stop')

        try:
            if args.control_dir:
                while not stopping:
                    consume_one(args.control_dir, handle)
                    if not stopping:
                        page.wait_for_timeout(100)
            else:
                for line in sys.stdin:
                    try:
                        print(json.dumps(handle(json.loads(line)), ensure_ascii=True), flush=True)
                    except Exception as error:
                        print(json.dumps({'type':'error','error_type':type(error).__name__}), flush=True)
                    if stopping:
                        break
        finally:
            context.close()
            if browser is not None:
                browser.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--control-dir', type=Path, help='Local mailbox; no dependency on stdin')
    parser.add_argument('--keep-login', action='store_true',
                        help='Explicit opt-in: retain login in a dedicated test profile')
    args = parser.parse_args(argv)
    with control_lock(args.control_dir) if args.control_dir else nullcontext():
        run_browser(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
