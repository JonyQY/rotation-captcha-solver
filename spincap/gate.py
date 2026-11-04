# -*- coding: utf-8 -*-
"""Consensus gate based on circular distance, an explicit reference and seam rejection.

Agreement between readers is a heuristic, not a guarantee of independent errors
or of a correct orientation."""
from dataclasses import dataclass, field, asdict
import math

from .metrics import FULL_TURN, circular_distance, is_near_seam, spread


@dataclass
class GateConfig:
    """门控参数。

    字段
        tiers            参与表决的读图来源
        baseline         基准来源。空则取 tiers 里第一个读出值的。
                         显式指定比依赖顺序更安全：顺序一变基准就变，
                         而基准决定下注角度，这个耦合不该藏在列表顺序里。
        agree_gap        跟随票的容差，单位度
        min_agreeing     除基准外至少需要几票跟随
        seam_tolerance   基准落在零度接缝这么近时，判为不稳，换图
        max_refreshes    连续换图次数上限
        max_spread       读数整体的最大离散度，超过直接换图
    """

    tiers: tuple = ('pico', 'nano', 'fast', 'max')
    baseline: str = None
    agree_gap: float = 20.0
    min_agreeing: int = 2
    seam_tolerance: float = 6.0
    max_refreshes: int = 8
    max_spread: float = None

    def as_dict(self):
        return asdict(self)


@dataclass
class GateDecision:
    """门控的判决结果。"""

    usable: bool
    angle: float = None
    source: str = ''
    agreeing: int = 0
    reason: str = ''
    detail: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


def decide(readings, config=None):
    """根据一组读数判断这张图能不能下注。

    参数
        readings   字典，键是来源名，值是角度；值为 None 表示该来源读失败
        config     GateConfig，不给就用默认值

    返回
        GateDecision

    判定顺序
        一、基准来源必须读成功，否则换图
        二、基准不能贴在接缝上，否则换图
        三、跟随票数必须达到门槛，否则换图
        四、若设了最大离散度，整体超过也换图
    """
    if config is None:
        config = GateConfig()

    usable_readings = {name: float(value) % FULL_TURN for name, value in readings.items()
                       if isinstance(value, (int, float)) and not isinstance(value, bool)
                       and math.isfinite(value) and name in config.tiers}

    if not usable_readings:
        return GateDecision(False, reason='没有任何来源读出角度')

    # The baseline decides which angle gets submitted, so it must not be an accident of the
    # tier ordering. An explicit baseline is used when given; otherwise the first configured
    # tier that produced a value wins, and a failed tier falls through to the next.
    baseline_source = None
    if config.baseline:
        if config.baseline not in usable_readings:
            return GateDecision(False, reason='指定基准来源未读出有效角度')
        baseline_source = config.baseline
    else:
        for tier in config.tiers:
            if tier in usable_readings:
                baseline_source = tier
                break

    if baseline_source is None:
        baseline_source = next(iter(usable_readings))

    baseline = usable_readings[baseline_source]

    # Agreement is computed before any rejection so that every rejection can report it.
    # Returning early with a blank count made the two failure modes indistinguishable in the
    # report: a caller could not tell "the baseline sits on the seam" from "too few tiers agree".
    agreeing = sum(
        1 for name, value in usable_readings.items()
        if name != baseline_source
        and circular_distance(value, baseline) <= config.agree_gap)

    agrees_with = [name for name, value in usable_readings.items()
                   if name != baseline_source
                   and circular_distance(value, baseline) <= config.agree_gap]

    detail = {
        'readings': usable_readings,
        'baseline': baseline,
        'baselineSource': baseline_source,
        'agreeing': agreeing,
        'agreesWith': agrees_with,
    }

    if is_near_seam(baseline, config.seam_tolerance):
        decision_detail = dict(detail)
        decision_detail['seam'] = round(
            min(baseline, FULL_TURN - baseline), 3)
        return GateDecision(
            False, angle=baseline, source=baseline_source, agreeing=agreeing,
            reason=f'基准 {baseline_source} 读数 {baseline:.2f}° 贴着零度接缝，'
                   f'换算出的位移会顶到轨道端点',
            detail=decision_detail)

    if agreeing < config.min_agreeing:
        return GateDecision(
            False, angle=baseline, source=baseline_source, agreeing=agreeing,
            reason=f'基准 {baseline_source} 读数 {baseline:.2f}°，'
                   f'只有 {agreeing} 票跟随，低于门槛 {config.min_agreeing}',
            detail=detail)

    if config.max_spread is not None:
        overall = spread(usable_readings.values())
        detail['spread'] = overall
        if overall > config.max_spread:
            return GateDecision(
                False, angle=baseline, source=baseline_source, agreeing=agreeing,
                reason=f'整体离散度 {overall:.2f}° 超过上限 {config.max_spread}°',
                detail=detail)

    return GateDecision(
        True, angle=baseline, source=baseline_source, agreeing=agreeing,
        reason=f'基准 {baseline_source} 读数 {baseline:.2f}°，'
               f'{agreeing} 票跟随，可用',
        detail=detail)


class Gate:
    """有状态的便捷包装：记忆换图次数，达到上限时给出明确信号。"""

    def __init__(self, config=None):
        self.config = config or GateConfig()
        self.refreshes = 0

    def reset(self):
        self.refreshes = 0

    def evaluate(self, readings):
        decision = decide(readings, self.config)
        if not decision.usable:
            if self.refreshes >= self.config.max_refreshes:
                decision.detail['exhausted'] = True
                decision.reason += f'；已换图 {self.refreshes} 次，达到上限'
            else:
                self.refreshes += 1
        return decision
