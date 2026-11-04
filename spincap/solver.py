# -*- coding: utf-8 -*-
"""求解器：把读图、门控、换算、拖动串成一条可编排的流程。

职责边界
    这个类不碰浏览器。它只做三件事：
        一、拿到一张图，用多个读图器各读一次，过门控
        二、门控通过就把角度换算成位移，交给调用方去执行拖动
        三、门控不通过就调用调用方给的换图函数，重来

    浏览器由调用方以三个回调注入：
        fetch_image()    取当前题的图，返回可被读图器接受的路径
        refresh()        换一张图，返回 True 表示换成功
        drag(offset)     按像素位移执行拖动，返回 True 表示拖成功

    这样同一套求解逻辑既能跑在 Playwright 上，
    也能跑在别的自动化框架上，还能纯离线跑测试。

判定结果
    通过与否由调用方在拖动之后告诉求解器，
    因为「怎么算通过」完全取决于站点，
    有的看某个元素出现，有的看接口返回，有的看业务是否成功。
    求解器只负责记录，不做猜测。
"""
import time

from .gate import Gate, GateConfig
from .metrics import to_offset, to_offset_complement
from .readers import file_digest
from .round import Attempt, ChallengeRound, Reading, SolveReport


class RotationSolver:
    """旋转验证码的通用求解器。

    构造参数
        readers          读图器列表，顺序即优先级，第一个最可靠
        config           门控参数
        pixels_per_turn  轨道上转满一圈对应的像素数
        complement       True 表示位移取补角。百度是 True，天爱云是 False
        track_span       轨道可用长度，给了就对位移做上限截断
    """

    def __init__(self, readers, config=None, pixels_per_turn=237.5,
                 complement=False, track_span=None):
        if not readers:
            raise ValueError('至少需要一个读图器')

        self.readers = list(readers)
        self.config = config or GateConfig(
            tiers=tuple(reader.name for reader in self.readers))
        self.pixels_per_turn = pixels_per_turn
        self.complement = complement
        self.track_span = track_span

    def convert(self, angle):
        """把角度换算成像素位移。"""
        if self.complement:
            return to_offset_complement(angle, self.pixels_per_turn,
                                        self.track_span)
        return to_offset(angle, self.pixels_per_turn, self.track_span)

    def read_all(self, image):
        """用全部读图器读一次，失败的记为 None 并保留错误原因。"""
        readings = {}
        errors = {}
        for reader in self.readers:
            try:
                value = reader.predict(image)
                readings[reader.name] = (round(float(value), 4)
                                         if value is not None else None)
            except Exception as error:
                readings[reader.name] = None
                errors[reader.name] = str(error)[:120]
        return readings, errors

    def solve_one(self, index, fetch_image, refresh, drag, verify,
                  on_event=None):
        """解一道题。

        参数
            index        题号，写进报告
            fetch_image  无参回调，返回图片路径
            refresh      无参回调，返回 True 表示换图成功
            drag         回调，接收像素位移，返回 True 表示拖动完成
            verify       无参回调，返回 (passed, outcome)，
                         由调用方定义什么算通过
            on_event     可选回调，接收 (阶段名, 数据字典)，用于录制与日志

        返回
            ChallengeRound
        """
        emit = on_event or (lambda stage, payload: None)
        record = ChallengeRound(index=index)
        gate = Gate(self.config)

        accepted = None
        attempt_index = 0

        for _ in range(self.config.max_refreshes + 1):
            image = fetch_image()
            if not image:
                emit('取图失败', {'题号': index})
                break

            record.image = file_digest(image)
            readings, errors = self.read_all(image)

            attempt = Attempt(index=attempt_index, readings=readings)
            decision = gate.evaluate(readings)
            attempt.agreed = decision.agreeing
            attempt.accepted = decision.usable
            attempt.note = decision.reason
            record.add_attempt(attempt)

            emit('读图', {
                '题号': index,
                '读数': readings,
                '错误': errors,
                '判定': '可用' if decision.usable else '换图',
                '理由': decision.reason,
            })
            attempt_index += 1

            if decision.usable:
                accepted = decision
                break

            if decision.detail.get('exhausted'):
                emit('换图达上限', {'题号': index, '次数': gate.refreshes})
                break

            if not refresh():
                emit('换图失败', {'题号': index})
                break

            record.refreshes += 1
            emit('换图', {'题号': index, '第几次': record.refreshes})

        if accepted is None:
            emit('跳过', {'题号': index, '原因': '读数未收敛'})
            record.outcome = 'no-consensus'
            return record

        record.chosen_angle = accepted.angle
        record.chosen_source = accepted.source
        record.offset = round(self.convert(accepted.angle), 2)

        emit('下注', {
            '题号': index,
            '角度': accepted.angle,
            '来源': accepted.source,
            '一致': accepted.agreeing,
            '位移': record.offset,
        })

        started = time.time()
        dragged = drag(record.offset)
        record.drag_ms = int((time.time() - started) * 1000)

        if not dragged:
            record.outcome = 'drag-failed'
            emit('拖动失败', {'题号': index})
            return record

        passed, outcome = verify()
        record.verdict_ms = int((time.time() - started) * 1000) - record.drag_ms
        record.passed = passed
        record.outcome = outcome or ('success' if passed else 'fail')

        emit('判定', {
            '题号': index,
            '通过': passed,
            '结果': record.outcome,
            '拖动毫秒': record.drag_ms,
            '判定毫秒': record.verdict_ms,
        })

        return record

    def solve(self, count, fetch_image, refresh, drag, verify,
              on_event=None, config_snapshot=None):
        """解若干道题，返回完整报告。"""
        report = SolveReport(config=config_snapshot or {
            'readers': [reader.name for reader in self.readers],
            'pixelsPerTurn': self.pixels_per_turn,
            'complement': self.complement,
            'trackSpan': self.track_span,
            'gate': self.config.as_dict(),
        })
        report.started = time.time()

        for index in range(count):
            report.add(self.solve_one(index, fetch_image, refresh, drag,
                                      verify, on_event))

        report.finished = time.time()
        return report
