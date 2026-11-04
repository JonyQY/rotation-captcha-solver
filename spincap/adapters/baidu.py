# -*- coding: utf-8 -*-
"""Historical Baidu DOM adapter.

Selectors and geometry are reference values from an older integration and need
verification against the current page. No live-site success rate is guaranteed."""
import base64
import time


AWAIT_IMAGE = """async () => {
    const wrap = document.querySelector('.passMod_spin-wrapper');
    if (!wrap) return null;
    const img = wrap.querySelector('img.passMod_spin-background');
    if (!img) return null;
    for (let i = 0; i < 100; i++) {
        if (img.complete && img.naturalWidth > 0) break;
        await new Promise(r => setTimeout(r, 40));
    }
    if (!img.complete || img.naturalWidth === 0) return {ok: false};
    try { await img.decode(); } catch (error) {}
    return {ok: true, src: img.src};
}"""

GEOMETRY = """() => {
    const wrap = document.querySelector('.passMod_spin-wrapper');
    if (!wrap) return null;
    const img = wrap.querySelector('img.passMod_spin-background');
    if (!img) return null;
    const rect = (selector) => {
        const el = wrap.querySelector(selector);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {x: r.x + r.width / 2, y: r.y + r.height / 2,
                w: r.width, h: r.height};
    };
    return {handle: rect('.passMod_slide-btn'),
            track: rect('.passMod_slide-control'), src: img.src};
}"""

REFRESH_CLICK = """() => {
    const node = document.querySelector('.passMod_dialog-footer-refresh');
    if (!node) return {ok: false};
    const box = node.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return {ok: false};
    return {ok: true, x: box.x + box.width / 2, y: box.y + box.height / 2};
}"""

# Presence is useless here: all four state nodes stay in the DOM and only their computed
# visibility changes, so the check has to read display/visibility/opacity.
VERDICT = """() => {
    const state = (token) => {
        const el = document.querySelector('[class*="' + token + '"]');
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return (style.display !== 'none' && style.visibility !== 'hidden'
                && parseFloat(style.opacity || '1') > 0.01);
    };
    return {success: state('passMod_verify-success'),
            fail: state('passMod_verify-fail')};
}"""

# The image is fetched from inside the page with its own credentials, then handed back as
# base64. Downloading the URL out of band loses the cookie and returns a placeholder.
FETCH_SRC = """async (src) => {
    const response = await fetch(src, {credentials: 'include'});
    if (!response.ok) return {ok: false, status: response.status};
    const buffer = await response.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return {ok: true, size: bytes.length, b64: btoa(binary)};
}"""

PIXELS_PER_TURN = 237.5
COMPLEMENT = True
SEAM_TOLERANCE = 6.0


class BaiduSpinAdapter:
    """驱动百度旋转验证码的控件，把站点的四个动作交给求解器。

    用法
        adapter = BaiduSpinAdapter(page, cdp, work_dir)
        adapter.open()
        solver.solve(n, adapter.fetch_image, adapter.refresh,
                     adapter.drag, adapter.verify)
    """

    name = 'baidu'

    def __init__(self, page, cdp, work_dir, trigger_js=None,
                 trigger_selectors=None):
        self.page = page
        self.cdp = cdp
        self.work_dir = work_dir
        self.trigger_js = trigger_js
        self.trigger_selectors = trigger_selectors or (
            '#saveBtn', 'button:has-text("提 交")')
        self.geometry = None
        self._sequence = 0

    def open(self, timeout=45000):
        """唤出验证码对话框。

        具体怎么唤出取决于页面，因此触发器由调用方给。
        给了选择器就点选择器，给了脚本就执行脚本。
        """
        if self.trigger_selectors:
            for selector in self.trigger_selectors:
                locator = self.page.locator(selector)
                try:
                    if locator.count() > 0 and locator.first.is_visible():
                        locator.first.click(timeout=timeout)
                        break
                except Exception:
                    continue

        if self.trigger_js:
            try:
                self.page.evaluate(self.trigger_js)
            except Exception:
                pass

        state = self.page.evaluate(AWAIT_IMAGE)
        return bool(state and state.get('ok'))

    def wait_ready(self, timeout=20.0):
        """等旋转图加载完成。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.page.evaluate(AWAIT_IMAGE)
            if state and state.get('ok'):
                return True
            self.page.wait_for_timeout(300)
        return False

    def fetch_image(self):
        """取当前题的图，存到工作目录，返回路径。"""
        geometry = self.page.evaluate(GEOMETRY)
        if not geometry or not geometry.get('src'):
            return None
        self.geometry = geometry

        fetched = self.page.evaluate(FETCH_SRC, geometry['src'])
        if not (fetched and fetched.get('ok') and fetched.get('size', 0) > 8000):
            return None

        self._sequence += 1
        path = self.work_dir / f'puzzle_{self._sequence:05d}.png'
        path.write_bytes(base64.b64decode(fetched['b64']))
        return path

    def refresh(self):
        """点刷新换一张图。"""
        info = self.page.evaluate(REFRESH_CLICK)
        if not info.get('ok'):
            return False
        self.page.mouse.click(info['x'], info['y'])
        self.page.wait_for_timeout(1300)
        state = self.page.evaluate(AWAIT_IMAGE)
        return bool(state and state.get('ok'))

    def drag(self, offset, points=6, step_pause=0.008, jitter=True):
        """按像素位移拖动滑块。

        用一次性的批量事件而不是逐次调用鼠标接口：
        逐次调用每次都要一个往返，六点拖动会从约六十五毫秒涨到两秒以上，
        轨迹的时间分布被破坏，看起来就不像人。
        """
        import random

        geometry = self.geometry
        if not geometry or not geometry.get('handle'):
            return False

        handle = geometry['handle']
        track = geometry.get('track') or {}
        hx, hy = handle['x'], handle['y']

        span = None
        if track.get('w') and handle.get('w'):
            span = track['w'] - handle['w']
        if span is not None:
            offset = min(offset, span)

        rng = random.Random()

        self.cdp.send('Input.dispatchMouseEvent',
                      {'type': 'mouseMoved', 'x': hx, 'y': hy, 'button': 'none'})
        self.cdp.send('Input.dispatchMouseEvent',
                      {'type': 'mousePressed', 'x': hx, 'y': hy, 'button': 'left',
                       'buttons': 1, 'clickCount': 1})

        for point in range(1, points + 1):
            fraction = 1.0 - (1.0 - point / points) ** 1.8
            y = hy + (rng.choice([-1, 0, 1]) if jitter else 0)
            self.cdp.send('Input.dispatchMouseEvent',
                          {'type': 'mouseMoved', 'x': hx + offset * fraction,
                           'y': y, 'button': 'left', 'buttons': 1})
            time.sleep(step_pause)

        self.cdp.send('Input.dispatchMouseEvent',
                      {'type': 'mouseReleased', 'x': hx + offset, 'y': hy,
                       'button': 'left', 'buttons': 0, 'clickCount': 1})
        return True

    def verify(self, timeout=4.0):
        """读判定。

        返回 (是否通过, 状态名)。
        这里只读验证控件的可见状态。
        它有一个已知的局限：弹层消失不等于业务动作成功，
        真正可靠的通过信号是业务页面出现成功提示。
        调用方如果关心这个更强的信号，应当在外面自行确认。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.page.wait_for_timeout(100)
            state = self.page.evaluate(VERDICT)
            if state.get('fail'):
                return False, 'fail'
            if state.get('success'):
                return True, 'success'
        return False, 'timeout'

    def is_dialog_gone(self):
        """弹层是否已消失。用作辅助信号，不单独作为通过判据。"""
        return self.page.evaluate("""() => {
            const wrap = document.querySelector('.passMod_spin-wrapper');
            if (!wrap) return true;
            const style = window.getComputedStyle(wrap);
            return (style.display === 'none' || style.visibility === 'hidden'
                    || parseFloat(style.opacity || '1') < 0.01);
        }""")
