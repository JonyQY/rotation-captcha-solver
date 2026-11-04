# -*- coding: utf-8 -*-
"""Optional orientation reader interfaces.

RightWayUp is developed by ORTUS AI and distributed separately. Different tiers
use different models or input resolutions; their errors need not be independent."""
import hashlib
from pathlib import Path


class OrientationReader:
    """读图器的基类。子类只需要实现 predict。

    名字用于门控里的优先级顺序与记录，
    所以要能一眼看出它是什么模型、什么尺度。
    """

    name = 'reader'

    def predict(self, image):
        """返回图片被顺时针旋转的角度，单位度，范围 [0, 360)。

        参数 image 可以是路径，也可以是字节。
        """
        raise NotImplementedError


class CallableReader(OrientationReader):
    """把任意函数包成读图器。

    用途
        已有的识别能力不必改写成类，包一层就能接进门控。
        例如一个用 ddddocr 的函数、一个调远端接口的函数、
        或者一个返回固定值的假函数用于测试。
    """

    def __init__(self, name, function):
        self.name = name
        self._function = function

    def predict(self, image):
        return self._function(image)


class FunctionReader(CallableReader):
    """CallableReader 的别名，语义更直白。"""


class RightWayUpReader(OrientationReader):
    """Optional RightWayUp wrapper; retains the upstream confidence and abstain metadata."""

    def __init__(self, tier='max', name=None, abstain='standard'):
        try:
            from rightwayup import Orienter
        except ImportError as error:
            raise ImportError('Image recognition requires: python -m pip install "spincap[model]" '
                              '(or install ".[model]" from the repository).') from error
        self.tier = tier
        self.abstain = abstain
        self.name = name or f'rightwayup-{tier}'
        self._orienter = Orienter(tier=tier, abstain=abstain)
        self.last_confidence = None
        self.last_abstain = None

    @property
    def threshold(self):
        """这一档当前的弃权阈值，由包按量化格式选定。"""
        return float(self._orienter.threshold)

    def predict(self, image):
        result = self._orienter.predict(str(image))
        self.last_confidence = float(result.confidence)
        self.last_abstain = bool(result.abstain)
        return float(result.angle_cw)

    def predict_full(self, image):
        """读一次并返回全部字段，供需要置信度的地方使用。"""
        result = self._orienter.predict(str(image))
        self.last_confidence = float(result.confidence)
        self.last_abstain = bool(result.abstain)
        return {
            'angle': float(result.angle_cw),
            'confidence': float(result.confidence),
            'abstain': bool(result.abstain),
            'tier': result.tier,
            'threshold': float(self._orienter.threshold),
        }


def build_readers(specs, tiers=None):
    """按配置批量建读图器。

    参数
        specs   字典或列表。字典是 {名字: 可调用}；
                列表是 [(名字, 可调用), ...]
        tiers   需要的名字顺序，给了就按这个顺序返回，
                缺的名字会跳过而不是报错

    返回
        (读图器列表, 名字顺序)
    """
    if isinstance(specs, dict):
        items = list(specs.items())
    else:
        items = list(specs)

    readers = [CallableReader(name, function) for name, function in items]

    if tiers:
        by_name = {reader.name: reader for reader in readers}
        ordered = [by_name[name] for name in tiers if name in by_name]
        remaining = [reader for reader in readers if reader.name not in set(tiers)]
        readers = ordered + remaining

    return readers, [reader.name for reader in readers]


def file_digest(image):
    """给图片内容算一个短摘要，用于在报告里标识是哪一张图。

    用内容而不是文件名，因为同一张图可能被存成不同的临时文件名。
    """
    path = Path(image)
    if not path.exists():
        return str(image)[:16]

    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()[:16]
