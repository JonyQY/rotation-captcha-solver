# -*- coding: utf-8 -*-
"""通用适配器：换个站点只填选择器与换算参数。

为什么需要它
    百度那种写法把选择器写死在代码里。
    对第二个站点，选择器不同，但动作序列完全一样：
        等图加载、取图、点刷新、拖滑块、读判定。
    所以把这套动作抽成通用类，站点差异收敛成一组参数。

    这样接一个新站点的成本从「写一个适配模块」
    降到「填五个选择器和两个数字」。

参数说明
    root            根容器选择器
    image           旋转图的 img 选择器（相对 root）
    handle          滑块选择器
    track           轨道选择器
    refresh         刷新按钮选择器
    success         成功状态元素选择器（可用 class 片段）
    fail            失败状态元素选择器
    pixels_per_turn 轨道上转满一圈的像素数
    complement      位移是否取补角
"""
import base64
import time

from ..metrics import is_near_seam


GENERIC_AWAIT = """async ([root, image]) => {
    const box = document.querySelector(root);
    if (!box) return null;
    const img = box.querySelector(image);
    if (!img) return null;
    for (let i = 0; i < 100; i++) {
        if (img.complete && img.naturalWidth > 0) break;
        await new Promise(r => setTimeout(r, 40));
    }
    if (!img.complete || img.naturalWidth === 0) return {ok: false};
    try { await img.decode(); } catch (error) {}
    return {ok: true, src: img.src};
}"""

GENERIC_GEOMETRY = """([root, imageSelector, handleSelector, trackSelector]) => {
    const box = document.querySelector(root);
    if (!box) return null;
    const img = box.querySelector(imageSelector);
    if (!img) return null;
    const rect = (selector) => {
        const el = box.querySelector(selector);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return null;
        return {x: r.x + r.width / 2, y: r.y + r.height / 2,
                w: r.width, h: r.height};
    };
    return {handle: rect(handleSelector), track: rect(trackSelector),
            src: img.src};
}"""

GENERIC_REFRESH = """(selector) => {
    const node = document.querySelector(selector);
    if (!node) return {ok: false};
    const box = node.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return {ok: false};
    return {ok: true, x: box.x + box.width / 2, y: box.y + box.height / 2};
}"""

# A generic visibility test. Sites differ in whether they toggle the state nodes or keep them
# mounted, so this checks computed style rather than presence.
GENERIC_VERDICT = """([successSelector, failSelector]) => {
    const visible = (selector) => {
        if (!selector) return false;
        const el = document.querySelector(selector);
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return (style.display !== 'none' && style.visibility !== 'hidden'
                && parseFloat(style.opacity || '1') > 0.01);
    };
    return {success: visible(successSelector), fail: visible(failSelector)};
}"""

GENERIC_FETCH = """async (src) => {
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


class GenericSpinAdapter:
    """用一组选择器驱动任意旋转验证控件。

    例子
        adapter = GenericSpinAdapter(
            page, cdp, work_dir,
            root='#captcha-root',
            image='img.rotate-bg',
            handle='.slider-handle',
            track='.slider-track',
            refresh='.refresh-btn',
            success='.verify-success',
            fail='.verify-fail',
            pixels_per_turn=242.0,
            complement=False)
    """

    name = 'generic'

    def __init__(self, page, cdp, work_dir,
                 root, image, handle, track=None, refresh=None,
                 success=None, fail=None,
                 pixels_per_turn=237.5, complement=False,
                 min_image_bytes=8000, refresh_pause=1.3):
        self.page = page
        self.cdp = cdp
        self.work_dir = work_dir
        self.root = root
        self.image = image
        self.handle = handle
        self.track = track
        self.refresh_selector = refresh
        self.success = success
        self.fail = fail
        self.pixels_per_turn = pixels_per_turn
        self.complement = complement
        self.min_image_bytes = min_image_bytes
        self.refresh_pause = refresh_pause
        self.geometry = None
        self._sequence = 0

    def wait_ready(self, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.page.evaluate(GENERIC_AWAIT, [self.root, self.image])
            if state and state.get('ok'):
                return True
            self.page.wait_for_timeout(300)
        return False

    def fetch_image(self, retries=3):
        for _ in range(retries):
            geometry = self.page.evaluate(
                GENERIC_GEOMETRY,
                [self.root, self.image, self.handle, self.track or self.handle])
            if not geometry or not geometry.get('src'):
                self.page.wait_for_timeout(400)
                continue

            self.geometry = geometry
            fetched = self.page.evaluate(GENERIC_FETCH, geometry['src'])
            if not (fetched and fetched.get('ok')
                    and fetched.get('size', 0) > self.min_image_bytes):
                self.page.wait_for_timeout(400)
                continue

            self._sequence += 1
            path = self.work_dir / f'puzzle_{self._sequence:05d}.png'
            path.write_bytes(base64.b64decode(fetched['b64']))
            return path
        return None

    def refresh(self):
        if not self.refresh_selector:
            return False
        info = self.page.evaluate(GENERIC_REFRESH, self.refresh_selector)
        if not info.get('ok'):
            return False
        self.page.mouse.click(info['x'], info['y'])
        self.page.wait_for_timeout(int(self.refresh_pause * 1000))
        return self.wait_ready()

    def drag(self, offset, points=6, step_pause=0.008, jitter=True):
        import random

        geometry = self.geometry
        if not geometry or not geometry.get('handle'):
            return False

        box = geometry['handle']
        track = geometry.get('track') or {}
        hx, hy = box['x'], box['y']

        span = None
        if track.get('w') and box.get('w'):
            span = track['w'] - box['w']
        if span is not None and span > 0:
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
        if not self.success and not self.fail:
            return False, 'unconfigured'

        deadline = time.time() + timeout
        while time.time() < deadline:
            self.page.wait_for_timeout(100)
            state = self.page.evaluate(
                GENERIC_VERDICT, [self.success, self.fail])
            if self.fail and state.get('fail'):
                return False, 'fail'
            if self.success and state.get('success'):
                return True, 'success'
        return False, 'timeout'


def detect_geometry(page, root, image, handle, track=None):
    """探测一次几何量，返回可直接填进适配器的参数。

    用途是接新站点时先量一遍：
    轨道可用长度、手柄尺寸、以及由长度推出的每圈像素数。
    每圈像素数的正确取法不是拍一个数字，
    而是量出轨道能容纳的位移范围，
    因为多数站点都把整圈映射到轨道的可用长度上。
    """
    geometry = page.evaluate(
        GENERIC_GEOMETRY, [root, image, handle, track or handle])
    if not geometry:
        return None

    box = geometry.get('handle') or {}
    rail = geometry.get('track') or {}

    span = None
    if rail.get('w') and box.get('w'):
        span = round(rail['w'] - box['w'], 1)

    return {
        'handle': box,
        'track': rail,
        'trackSpan': span,
        'suggestedPixelsPerTurn': span,
        'note': '建议每圈像素数取轨道可用长度，'
                '因为多数站点把整圈映射到这段长度上',
    }
