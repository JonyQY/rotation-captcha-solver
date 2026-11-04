# -*- coding: utf-8 -*-
"""角度运算。纯函数，不依赖任何第三方库。

角度在这类验证码里连着出问题，全是因为它有两套约定：
    有的站点要求拖动的距离等于图的偏角，
    有的站点要求等于它的补角。
    而偏角本身又可能在零到三百六十之间任意取值，
    零点附近还常常是一个接缝，读数最容易出错。

    所以这里把三件事分开写清楚：
        归一化，把任意角度收进零到三百六十
        环形距离，算两个角度之间的真实间隔而不是直接相减
        换算，把角度换成轨道上的像素位移，补角另给一个函数
"""
import math

FULL_TURN = 360.0


def normalize(angle):
    """把任意角度收进 [0, 360)。

    负数与超过一圈的值都会正确回落。

    这里必须处理一个浮点陷阱：
    Python 的取模对极小的负数会给出恰好 360.0 而不是 0.0，
    因为 360 减去一亿分之一被舍入成了 360。
    于是 -1.65e-14 归一化后落在区间外，
    后面所有以 [0, 360) 为前提的比较都会出错。
    实测触发路径是圆均值，
    三十度与三百三十度的均值会算出负的极小值。
    """
    value = float(angle) % FULL_TURN

    # Round-off just below zero lands exactly on the upper bound, which is outside the
    # documented half-open range. Snap it back to zero.
    if value >= FULL_TURN:
        value = 0.0

    return value


def circular_distance(a, b):
    """两个角度在圆上的最短间隔，取值 [0, 180]。

    直接相减是不对的：三百五十九度与一度只差两度，
    但相减得三百五十八度，会被误判成严重分歧。
    这个函数是门控能正常工作的前提。
    """
    difference = abs((float(a) - float(b) + 180.0) % FULL_TURN - 180.0)
    return difference


def is_near(a, b, tolerance):
    """两个角度是否在容差之内。用于可读性更好的调用点。"""
    return circular_distance(a, b) <= tolerance


def to_offset(angle, pixels_per_turn, track_span=None):
    """同向换算：位移等于角度对应弧长。

    参数
        angle            要转过的角度
        pixels_per_turn  轨道上转满一圈对应的像素数
        track_span       轨道可用长度，给了就做上限截断

    返回
        像素位移，非负
    """
    offset = normalize(angle) / FULL_TURN * float(pixels_per_turn)
    if track_span is not None:
        offset = min(offset, float(track_span))
    return offset


def to_offset_complement(angle, pixels_per_turn, track_span=None):
    """反向换算：位移等于补角对应弧长。

    有些站点的图是往一个方向偏的，而滑块只能往另一个方向拉，
    于是实际位移是三百六十度减去读数。
    百度就是这一类，用错这一个函数会让通过率直接归零。
    """
    return to_offset(FULL_TURN - normalize(angle), pixels_per_turn, track_span)


def is_near_seam(angle, tolerance):
    """读数是否落在零度接缝附近。

    这类图在零度两侧都接近正立，模型容易给出三百五十九或零度附近的读数，
    而轨道两端本身也是接缝，此时换算出的位移可能贴在轨道的极限位置，
    拖动会被截断，误差被放大。
    遇到这种情况更稳的做法是换一张图，而不是硬拖。
    """
    return min(normalize(angle), FULL_TURN - normalize(angle)) <= tolerance


def circular_mean(angles, weights=None):
    """一组角度的圆均值。

    算术平均对角度是错的：一度和三百五十九度的平均应当是零度，
    算术平均给的是三百六十度再归一化成零，
    而三十度和三百三十度的算术平均给一百八十度，完全偏离。
    圆均值通过转成单位向量再平均来避免这一点。

    权重可以用来做加权表决。
    """
    values = list(angles)
    if not values:
        raise ValueError('至少需要一个角度')

    if weights is None:
        weights = [1.0] * len(values)
    if len(weights) != len(values):
        raise ValueError('权重数量与角度数量不一致')

    total = sum(weights)
    if total == 0:
        raise ValueError('权重之和为零')

    x = 0.0
    y = 0.0
    for angle, weight in zip(values, weights):
        radians = math.radians(float(angle))
        x += weight * math.cos(radians)
        y += weight * math.sin(radians)

    x /= total
    y /= total

    # Degenerate case: angles spread evenly around the circle have no mean direction.
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        return None

    return normalize(math.degrees(math.atan2(y, x)))


def spread(angles):
    """一组角度在圆上的离散程度，取值 [0, 180]。

    取圆均值为中心，返回最大的圆距离。
    没有圆均值时说明这些角度互相抵消，返回上界。
    """
    values = [float(value) for value in angles]
    if len(values) < 2:
        return 0.0

    centre = circular_mean(values)
    if centre is None:
        return 180.0

    return max(circular_distance(value, centre) for value in values)
