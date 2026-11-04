# -*- coding: utf-8 -*-
"""Optional orientation reader interfaces.

RightWayUp is developed by ORTUS AI and distributed separately. Different tiers
use different models or input resolutions; their errors need not be independent."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

MODEL_FILES = {
    'pico': 'pico-s70-int8.onnx',
    'nano': 'nano-s112-int8.onnx',
    'fast': 'fast-s224-int8.onnx',
    'max': 'max-l280-int8.onnx',
}


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _assembled_model(directory, filename):
    """Assemble a sharded weight in a user cache and verify the original hash."""
    manifest = directory / 'manifest.json'
    if not manifest.is_file():
        return None
    metadata = json.loads(manifest.read_text(encoding='utf-8'))
    entry = next((item for item in metadata['files'] if item['name'] == filename), None)
    if not entry or not entry.get('parts'):
        return None
    digest = entry['sha256']
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid model checksum in manifest')
    parts = entry['parts']
    for index, name in enumerate(parts, 1):
        if name != f'{filename}.part{index:03d}':
            raise ValueError('Invalid model part name in manifest')
        part = directory / name
        if not part.is_file():
            raise FileNotFoundError('Model part is missing. Run git lfs pull, then reinstall.')
        with part.open('rb') as stream:
            if stream.read(80).startswith(b'version https://git-lfs.github.com/spec/v1'):
                raise RuntimeError('Model parts are Git LFS pointers. Run git lfs pull, then reinstall.')
    cache_base = os.environ.get('SPINCAP_CACHE_DIR')
    cache = (Path(cache_base) if cache_base else Path.home() / '.cache' / 'spincap') / digest
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / filename
    if target.is_file() and target.stat().st_size == entry['bytes'] and _file_hash(target) == digest:
        return target
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, suffix='.tmp', delete=False) as stream:
            temp_path = Path(stream.name)
            for name in parts:
                with (directory / name).open('rb') as part:
                    for chunk in iter(lambda: part.read(1024 * 1024), b''):
                        stream.write(chunk)
        if temp_path.stat().st_size != entry['bytes'] or _file_hash(temp_path) != digest:
            raise ValueError('Model checksum mismatch. Run git lfs pull and reinstall the package.')
        os.replace(temp_path, target)
        return target
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def local_model_dir(tier, model_dir=None):
    """Resolve packaged weights without downloading or reading a user cache."""
    if tier not in MODEL_FILES:
        raise ValueError('Supported tiers: pico, nano, fast, max')
    configured = model_dir or os.environ.get('SPINCAP_MODEL_DIR')
    directory = Path(configured) if configured else Path(__file__).parent / 'models'
    path = directory / MODEL_FILES[tier]
    if not path.is_file():
        assembled = _assembled_model(directory, MODEL_FILES[tier])
        if assembled is not None:
            return assembled.parent
        raise FileNotFoundError('Local model is missing. Run git lfs install && git lfs pull '
                                'in the repository, then reinstall the package.')
    with path.open('rb') as stream:
        if stream.read(80).startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise RuntimeError('Only a Git LFS pointer was downloaded. Run git lfs pull '
                               'in the repository, then reinstall the package.')
    return directory


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

    def __init__(self, tier='max', name=None, abstain='standard', model_dir=None):
        try:
            from rightwayup import Orienter
        except ImportError as error:
            raise ImportError('Image recognition requires: python -m pip install "spincap[model]" '
                              '(or install ".[model]" from the repository).') from error
        self.tier = tier
        self.abstain = abstain
        self.name = name or f'rotation-{tier}'
        self._orienter = Orienter(tier=tier, abstain=abstain,
                                 model_dir=local_model_dir(tier, model_dir),
                                 device='cpu', precision='int8')
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
