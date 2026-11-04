# -*- coding: utf-8 -*-
"""高层接口：一行调用完成一道旋转验证码。

这一层是给「我只想把这个验证码过掉，不想读文档」的人准备的。

两个用法
    一、只想要角度，不管浏览器
        from spincap import read_angle
        angle = read_angle('puzzle.png')

    二、要完整跑通一个页面
        from spincap import solve_baidu
        report = solve_baidu(page, cdp, work_dir, count=10)

    angle 是图被顺时针旋转的角度，单位度。
    拿到它之后怎么换算成位移由站点决定，
    换算函数在 spincap.metrics 里，两个方向都有。
"""
from pathlib import Path

from .gate import GateConfig
from .metrics import to_offset, to_offset_complement
from .readers import CallableReader, RightWayUpReader, file_digest
from .solver import RotationSolver

DEFAULT_TIERS = ('pico', 'nano', 'fast', 'max')


def default_readers(tiers=DEFAULT_TIERS):
    """默认读图器：本机 rightwayup 的四个档位。

    不同档位使用不同模型或输入尺度。读数一致仅作为筛选条件，
    不代表它们统计独立，也不保证识别正确。
    """
    return [RightWayUpReader(tier=tier) for tier in tiers]


def _resolve(readers, tiers, baseline):
    """把调用方给的档位名映射到读图器实际的键名。

    为什么需要这一步
        读图器的键名带有模型来源，例如 rightwayup-max，
        而调用方说的是档位名 max。
        两者不同是有意的：键名要在报告里能看出是哪个模型读的，
        而调用方关心的是档位。
        但门控是按键名匹配的，所以这里必须显式翻译一次，
        否则基准会静默回退到列表第一个，
        表现为「明明指定了 max，结果却按 pico 下注」。
    """
    by_tier = {}
    by_name = {}
    for reader in readers:
        key = getattr(reader, 'name', None) or getattr(reader, 'tier', None)
        if key is None:
            continue
        by_name[key] = key
        tier = getattr(reader, 'tier', None)
        if tier:
            by_tier.setdefault(tier, key)

    def translate(value):
        if value is None:
            return None
        if value in by_name:
            return value
        if value in by_tier:
            return by_tier[value]
        return value

    return [translate(tier) for tier in tiers], translate(baseline)


def read_angle(image, tiers=DEFAULT_TIERS, require_agreement=True,
               agree_gap=20.0, min_agreeing=2, baseline='max'):
    """读一张图的角度。这是最常用的入口。

    参数
        image              图片路径，或任何能被读图器接受的对象
        tiers              用哪几个档位，例如 pico nano fast max
        require_agreement  是否要求多档一致。False 时只按基准档返回
        agree_gap          一致容差，单位度
        min_agreeing       至少几档跟随
        baseline           以哪一档为准。默认 max，与实测一致：
                           默认使用 max 档作为基准

    返回
        角度，单位度；读数不收敛时返回 None

    用法
        angle = read_angle('puzzle.png')
        if angle is None:
            print('这张图模型读不准，换一张')
    """
    readers = default_readers(tiers)
    readings = {}
    for reader in readers:
        try:
            value = reader.predict(image)
            readings[reader.name] = float(value) if value is not None else None
        except Exception:
            readings[reader.name] = None

    keys, baseline_key = _resolve(readers, tiers, baseline)

    if not require_agreement:
        if baseline_key and readings.get(baseline_key) is not None:
            return round(readings[baseline_key], 2)
        if baseline_key:
            return None
        for key in keys:
            if readings.get(key) is not None:
                return round(readings[key], 2)
        return None

    config = GateConfig(tiers=tuple(keys), baseline=baseline_key,
                        agree_gap=agree_gap, min_agreeing=min_agreeing)
    from .gate import decide
    decision = decide(readings, config)
    return round(decision.angle, 2) if decision.usable else None


def read_all(image, tiers=DEFAULT_TIERS):
    """读全部档位并原样返回，不做事后判断。

    想要自己做判决、或者想看分歧有多大时用这个。
    """
    readers = default_readers(tiers)
    result = {}
    for reader in readers:
        try:
            value = reader.predict(image)
            result[reader.name] = round(float(value), 4) if value is not None else None
        except Exception as error:
            result[reader.name] = None
            result.setdefault('errors', {})[reader.name] = str(error)[:120]
    return result


def offset_for(angle, pixels_per_turn, complement=False, track_span=None):
    """角度转位移。站点用补角就把 complement 置 True。"""
    if complement:
        return round(to_offset_complement(angle, pixels_per_turn, track_span), 2)
    return round(to_offset(angle, pixels_per_turn, track_span), 2)


def build_solver(readers=None, tiers=DEFAULT_TIERS, pixels_per_turn=237.5,
                 complement=False, track_span=None, agree_gap=20.0,
                 min_agreeing=2, seam_tolerance=6.0, max_refreshes=8,
                 baseline=None):
    """建一个求解器。默认读图器是本机的四档。

    baseline 不给时取读图器列表的第一个。
    需要固定基准时应显式指定 baseline。
    """
    if readers is None:
        readers = default_readers(tiers)

    readers = list(readers)
    names = [reader.name for reader in readers]
    if len(set(names)) != len(names):
        raise ValueError('Reader names must be unique')
    keys, baseline_key = _resolve(readers, tiers, baseline)
    if baseline_key is not None and baseline_key not in names:
        raise ValueError('Baseline must name a configured reader')
    ordered = [key for key in keys if key in names]
    ordered += [name for name in names if name not in ordered]

    config = GateConfig(tiers=tuple(ordered), baseline=baseline_key,
                        agree_gap=agree_gap,
                        min_agreeing=min_agreeing,
                        seam_tolerance=seam_tolerance,
                        max_refreshes=max_refreshes)
    return RotationSolver(readers, config=config,
                          pixels_per_turn=pixels_per_turn,
                          complement=complement, track_span=track_span)


def solve_baidu(page, cdp, work_dir, count=10, on_event=None,
                trigger_selectors=('#saveBtn', 'button:has-text("提 交")'),
                trigger_js=None, track_span=None):
    """在百度旋转验证码上跑一轮。

    参数已经按实测值配好：轨道 237.5 像素每圈，位移取补角，
    四档表决，两块跟随，接缝容差 6 度。
    这四个数字是量出来的，不要凭感觉改。
    """
    from .adapters.baidu import (
        BaiduSpinAdapter, PIXELS_PER_TURN, COMPLEMENT, SEAM_TOLERANCE)

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    adapter = BaiduSpinAdapter(page, cdp, work,
                               trigger_js=trigger_js,
                               trigger_selectors=trigger_selectors)

    solver = build_solver(pixels_per_turn=PIXELS_PER_TURN,
                          complement=COMPLEMENT,
                          track_span=track_span,
                          seam_tolerance=SEAM_TOLERANCE,
                          baseline='max')

    def fetch():
        return adapter.fetch_image()

    def refresh():
        return adapter.refresh()

    def drag(offset):
        return adapter.drag(offset)

    def verify():
        return adapter.verify()

    report = solver.solve(count, fetch, refresh, drag, verify,
                          on_event=on_event)
    return report


def solve_generic(page, cdp, work_dir, count=10,
                  root=None, image=None, handle=None, track=None,
                  refresh=None, success=None, fail=None,
                  pixels_per_turn=None, complement=False,
                  on_event=None, auto_measure=True):
    """在任意旋转验证控件上跑一轮。

    选择器必须给。轨道可用长度可以自动量，
    量出来之后建议把它作为每圈像素数，
    因为多数站点都把整圈映射到这段长度上。
    """
    from .adapters.generic import GenericSpinAdapter, detect_geometry

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    span = None
    if auto_measure and pixels_per_turn is None:
        measured = detect_geometry(page, root, image, handle, track)
        if measured:
            span = measured.get('trackSpan')
            pixels_per_turn = measured.get('suggestedPixelsPerTurn')

    if pixels_per_turn is None:
        pixels_per_turn = 237.5

    adapter = GenericSpinAdapter(
        page, cdp, work,
        root=root, image=image, handle=handle, track=track,
        refresh=refresh, success=success, fail=fail,
        pixels_per_turn=pixels_per_turn, complement=complement)

    solver = build_solver(pixels_per_turn=pixels_per_turn,
                          complement=complement, track_span=span)

    report = solver.solve(count, adapter.fetch_image, adapter.refresh,
                          adapter.drag, adapter.verify, on_event=on_event)
    return report
