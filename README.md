# 旋转图片算法模型

旋转验证码求解框架：**读取图片偏角 → 多档读数一致性筛选 → 换算滑块位移 → 由调用方验证结果**。

提供 Python API、命令行和浏览器回调接口，可独立使用，不依赖原来的复制粘贴工作台。
附带四档本地模型权重，提供图片角度识别、读数筛选和滑块位移换算。

## Agent 调用

仓库已附带标准技能文件：
[`.agents/skills/rotation-image-model/SKILL.md`](.agents/skills/rotation-image-model/SKILL.md)。
它包含环境准备、实际命令、JSON/退出码解释、Python 接入和权重恢复步骤。

克隆仓库后，在仓库中启动支持该目录的 Agent，并发送：

```text
使用 $rotation-image-model，识别 /absolute/path/puzzle.png 的旋转角度，返回实际 JSON 结果。
```

Codex 会发现仓库内 `.agents/skills` 中的技能，见
[官方技能目录说明](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)。
其他 Agent 可直接读取上述 `SKILL.md`，或把整个 `rotation-image-model` 技能文件夹
复制到该工具支持的技能目录。技能本身不携带权重；单独复制技能后，应按技能说明安装本仓库的求解器。
根目录的 [AGENTS.md](AGENTS.md) 也提供了调用入口。

有轨道参数时可以直接说明：

```text
使用 rotation-image-model 技能识别 /absolute/path/puzzle.png。
轨道每圈 240 像素、使用补角换算；返回角度和位移，不操作网页。
```

`240` 是示例参数，应替换为实际控件标定值。默认结果不可用时，技能会报告失败，
不会自动改用单档读数或将拖动完成冒充页面验证成功。

## 克隆并安装

需要 Python **3.10 或以上**，推荐 3.11–3.13，使用 64 位 Python。

```bash
git lfs install
git clone https://github.com/JonyQY/rotation-image-model.git
cd rotation-image-model
git lfs pull
python -m venv .venv
```

Windows PowerShell 激活：`.venv\Scripts\Activate.ps1`；macOS/Linux 激活：`source .venv/bin/activate`。
如果 PowerShell 不允许激活，直接用 `.venv\Scripts\python.exe` 替换下方的 `python` 即可。

```bash
python -m pip install --upgrade pip
python -m pip install ".[model]"
```

仓库包含约 **384 MB** 的 ONNX INT8 权重，通过 Git LFS 下载。克隆前先安装
[Git LFS](https://git-lfs.com/)。安装后直接读取本地权重，无需首次调用时另行下载模型。
最大模型采用分片存储，首次使用会自动合并到用户缓存目录并校验完整性；以后直接加载缓存。
默认使用 CPU，不需要 GPU、API 密钥或 PyTorch。

私密仓库需要先登录有权访问的 GitHub 账号；仓库公开后其他人即可直接克隆。
请按上面的克隆步骤安装，确保 Git LFS 已下载完整权重。

本项目目前通过 GitHub 分发；不要把 `pip install spincap` 当作本项目的安装地址。

## 最短 Python 调用

```python
from spincap import read_angle, offset_for

angle = read_angle("puzzle.png")
if angle is None:
    print("读数未通过一致性筛选，交由调用方换图或人工处理")
else:
    # 图像内容偏离正立方向的顺时针角度，单位：度。
    print("angle_cw:", angle)
    # 示例轨道参数，必须按你的控件实际标定。
    distance = offset_for(angle, pixels_per_turn=240, complement=True)
    print("offset_px:", distance)
```

`read_angle` 默认使用 `pico/nano/fast/max` 四档，以 `max` 为基准：至少另外两档
与基准的圆距离不超过 20°，且基准不落在零度前后 6° 内，才返回角度，否则返回 `None`。
角度为 `a` 表示图片需要逆时针转 `a` 度才能转正。滑块是否取补角必须单独确认。

只用一个档位（速度更快，跳过一致性及接缝筛选）：

```python
angle = read_angle("puzzle.png", tiers=("fast",),
                   baseline="fast", require_agreement=False)
```

查看各档位读数：

```python
from spincap import read_all
print(read_all("puzzle.png"))
```

连续识别或实时接入时，先创建会话，再获取题图，复用已经加载的模型：

```python
from spincap import AngleSession, offset_for

session = AngleSession()  # 在题目出现前加载一次四档模型
angle = session.read_angle("puzzle.png")
if angle is not None:
    print(offset_for(angle, 240, complement=True))
# 下一张继续 session.read_angle(next_image)，不重新创建会话。
```

`AngleSession` 保留与 `read_angle` 相同的默认筛选和基准规则，每次对新图片重新推理。
每个顺序执行的工作进程使用自己的会话；不要跨线程共享模型实例。
已有回调流程仍可用 `default_readers()` 初始化一次并复用于 `build_solver`。

## 命令行

```bash
python -m spincap puzzle.png
spincap puzzle.png --pixels-per-turn 240 --complement
spincap puzzle.png --tier fast
spincap puzzle.png --all
```

输出为 JSON，例如 `{"angle_cw": 90.0, "usable": true, "offset_px": 180.0}`。
退出码：`0` 有可用结果，`2` 没有共识/图片读取失败或参数错误，`1` 初始化或依赖错误。
`--all` 只列读数，不作共识判定。

### 常驻调用，避免每张图重新启动模型

```bash
python -m spincap --stdio
```

启动后先输出一行 `{"type":"ready","init_seconds":3.0}`（时间仅为示例）。
调用方等收到 `ready` 再获取题目；保持同一个进程和输入流开启，每行发送一个 JSON 请求：

```json
{"id":1,"image":"/absolute/path/puzzle.png","pixels_per_turn":240,"complement":true}
```

每条请求返回一行结果，含原样返回的 `id`、`type:"result"`、`angle_cw`、`usable`、
可选 `offset_px` 和 `elapsed_ms`。无共识时 `usable:false`；非法请求另含 `error`，
不会中止后续请求。`ready` 前初始化失败时退出码为 `1`，错误写入 stderr。
每条请求成功与否看结果的 `usable`/`error`，工作进程读到 EOF 后正常退出 `0`。
请求必须使用本地绝对路径；Windows 可写 `C:/images/puzzle.png`。

这是本地识图进程，不打开网络端口，也不操作浏览器。启动速度、单张推理速度与
网页取图/拖动耗时应分别记录；浏览器调用很慢时，单纯复用模型不能消除网页操作延迟。

## 无需模型的快速验证

只想先确认安装和回调流程是否正常，可以安装核心包：

```bash
python -m pip install .
python examples/offline_demo.py
python -m unittest discover -s tests -v
```

示例使用模拟读数，预期位移为 **60 px**；它不识别图片、不访问网站，也不证明真实验证码通过率。

## 接入自己的模型与自动化程序

`CallableReader(name, function)` 将任意 `function(image_path) -> angle_cw | None`
接入求解器。至少三个读图来源才能满足默认“两票跟随”的要求，也可以按实际需求配置 `min_agreeing`。

```python
from spincap import CallableReader, build_solver

readers = [CallableReader("model-a", model_a_predict),
           CallableReader("model-b", model_b_predict),
           CallableReader("model-c", model_c_predict)]
solver = build_solver(readers, baseline="model-a", pixels_per_turn=240,
                      complement=True, max_refreshes=3)
report = solver.solve(
    1,
    fetch_image=fetch_current_image,  # 返回本次题图的本地路径
    refresh=refresh_current_image,   # 返回 bool，图片更新后才返回 True
    drag=drag_slider,                # 接收像素位移，返回 bool
    verify=verify_result,            # 返回 (bool, outcome_string)
)
print(report.summary())
```

这段代码中的模型函数及四个回调需要由你的程序实现。完整可运行的回调示例见
[examples/offline_demo.py](examples/offline_demo.py)。
如果没有共识或拖动失败，`verify` 不会被调用，也不会报告成功。
`baseline` 显式指定后，不会因为该模型失败而静默改用其他模型。

## 可选浏览器适配

```bash
python -m pip install ".[all]"
python -m playwright install chromium
```

包内保留 `solve_generic`、`solve_baidu` 以及 `adapters` 作为接入参考。
它们使用 Playwright 的**同步** API，以及 Chromium CDP 会话
`cdp = page.context.new_cdp_session(page)`。请先导航到目标页面并打开本次验证码。
通用适配参数为 `root/image/handle/track/refresh/success/fail` 的 CSS 选择器；
`root` 内查找图片、滑块和轨道，刷新及判定选择器相对文档。
当前适配对象是普通 DOM 中的 `<img>`，并非 canvas、iframe 或所有厂商的验证码。

轨道长度与方向必须依据当前控件标定；旧百度适配中的 237.5 px 只是一组历史参数。
成功条件必须由实际页面或业务结果确认，拖动完成不等于通过。适配器没有在本次发布中
对第三方网站做在线通过率验证。

## 算法与限制

- 使用圆距离比较角度，例如 359° 和 1° 仅相差 2°。
- 读数一致性门控用于拒绝分歧较大的题图；接缝筛选用于避开轨道端点附近的不稳定换算。
- 提供 `pico/nano/fast/max` 四档；读数一致也可能同时出错，不能视为统计独立。
- 无明确朝向的图片可能无法识别；不同题图和控件需要分别验证效果。
- `read_angle` 的默认门控基于角度一致性及接缝；它不额外按模型的 `abstain` 标志过滤。
- 缺依赖、权重缺失会抛出初始化异常；`read_all` 会报告各档预测错误，`read_angle` 在预测失败时返回 `None`。
- 多次读取同一图片的固定模型，不能当作多个独立来源重复投票。

模型文件位于 `spincap/models/`，校验信息在 `manifest.json`。可以通过
`SPINCAP_MODEL_DIR` 指定另一个完整的本地模型目录，`SPINCAP_CACHE_DIR` 指定分片合并缓存目录。
如果提示只下载了 Git LFS 指针，请在仓库目录执行 `git lfs pull`，再重新安装。

## 许可与来源

spincap 代码使用 [MIT](LICENSE) 许可证。
模型及依赖的许可与来源见
[第三方组件说明](THIRD_PARTY_NOTICES.md)。仓库包含算法模块、四档模型权重、调用示例和测试。
