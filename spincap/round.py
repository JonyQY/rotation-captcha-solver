# -*- coding: utf-8 -*-
"""一次挑战的状态容器。与浏览器、网络、模型都无关。

为什么要有这一层
    求解过程里最容易被写乱的是状态：
    当前是第几轮、这一张图刷了几次、每个档位读了什么、
    哪一次读数被判可用、最后提交的位移是多少。
    如果把这些散落在主循环的局部变量里，
    换一个站点就要重新理一遍，而且很难回放。

    这里把它们收进一个对象，任何一次求解都能被完整序列化，
    事后可以逐字节重放判定过程。
"""
import json
from dataclasses import dataclass, field, asdict


@dataclass
class Reading:
    """单个读数来源给出的一次结果。"""

    source: str
    angle: float
    ok: bool = True
    error: str = ''

    def as_dict(self):
        return asdict(self)


@dataclass
class Attempt:
    """对同一张图的一次读数尝试。"""

    index: int
    readings: dict = field(default_factory=dict)
    agreed: int = 0
    accepted: bool = False
    note: str = ''

    def angles(self):
        return {name: value for name, value in self.readings.items()
                if isinstance(value, (int, float))}

    def as_dict(self):
        return asdict(self)


@dataclass
class ChallengeRound:
    """一道题从取图到判定的完整记录。

    字段
        index          第几题，从零开始
        image          这一题图的来源标识，可以是路径、摘要或地址
        attempts       对这张图的历次读数，含刷新前后的
        chosen_angle   最终下注的角度，未通过门控时为空
        chosen_source  这个角度来自哪个读数来源
        offset         换算出的像素位移
        outcome        站点的判定结果，由适配层回填
        passed         是否通过，未提交时为 None
    """

    index: int
    image: str = ''
    attempts: list = field(default_factory=list)
    chosen_angle: float = None
    chosen_source: str = ''
    offset: float = None
    outcome: str = ''
    passed: bool = None
    refreshes: int = 0
    drag_ms: int = 0
    verdict_ms: int = 0

    def add_attempt(self, attempt):
        self.attempts.append(attempt)
        return attempt

    @property
    def last_attempt(self):
        return self.attempts[-1] if self.attempts else None

    def as_dict(self):
        payload = asdict(self)
        payload['attempts'] = [item.as_dict() for item in self.attempts]
        return payload


@dataclass
class SolveReport:
    """一次批量求解的全部记录。"""

    rounds: list = field(default_factory=list)
    config: dict = field(default_factory=dict)
    started: float = 0.0
    finished: float = 0.0

    def add(self, item):
        self.rounds.append(item)
        return item

    @property
    def submitted(self):
        return [item for item in self.rounds if item.passed is not None]

    @property
    def passed(self):
        return [item for item in self.rounds if item.passed]

    def summary(self):
        submitted = len(self.submitted)
        passed = len(self.passed)
        rejected = [item for item in self.rounds if item.passed is None]
        return {
            'rounds': len(self.rounds),
            'submitted': submitted,
            'passed': passed,
            'rate': round(passed / submitted, 4) if submitted else 0.0,
            'refreshedOut': len(rejected),
            'refreshes': sum(item.refreshes for item in self.rounds),
            'elapsed': round(self.finished - self.started, 2) if self.finished else 0.0,
        }

    def as_dict(self):
        return {
            'summary': self.summary(),
            'config': self.config,
            'rounds': [item.as_dict() for item in self.rounds],
        }

    def save(self, path):
        from pathlib import Path
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2),
            encoding='utf-8')
        return target
