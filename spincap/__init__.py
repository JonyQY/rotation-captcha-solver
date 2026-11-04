# -*- coding: utf-8 -*-
"""Rotation challenge toolkit: angle utilities, consensus gates, readers and adapters.

Image orientation is provided by optional third-party models; consensus does not
guarantee that an angle is correct. Site behavior is supplied by the caller."""
from .metrics import circular_distance, normalize, to_offset, to_offset_complement
from .round import ChallengeRound, Reading
from .gate import GateConfig, GateDecision, decide
from .readers import CallableReader, OrientationReader, RightWayUpReader
from .solver import RotationSolver
from .api import (
    build_solver, default_readers, offset_for, read_angle, read_all,
    solve_baidu, solve_generic,
)

__all__ = [
    # 角度运算
    'circular_distance', 'normalize', 'to_offset', 'to_offset_complement',
    'offset_for',
    # 状态
    'ChallengeRound', 'Reading',
    # 门控
    'GateConfig', 'GateDecision', 'decide',
    # 读图接口
    'OrientationReader', 'CallableReader', 'RightWayUpReader',
    'default_readers', 'read_angle', 'read_all',
    # 求解
    'RotationSolver', 'build_solver', 'solve_baidu', 'solve_generic',
    '__version__',
]

__version__ = '1.0.0'
