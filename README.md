# spincap

旋转验证码求解框架：**读取图片偏角 → 多档读数一致性筛选 → 换算滑块位移 → 由调用方验证结果**。

提供 Python API、命令行和浏览器回调接口，可独立使用，不依赖原来的复制粘贴工作台。
核心算法零第三方依赖；内置图片识别由 ORTUS AI 的 [RightWayUp](https://github.com/ortusaitech/rightwayup) 提供。

## 克隆并安装

需要 Python **3.10 或以上**，推荐 3.11–3.13，使用 64 位 Python。

```bash
git clone https://github.com/JonyQY/spincap.git
cd spincap
python -m venv .venv
```

Windows PowerShell 激活：`.venv\Scripts\Activate.ps1`；macOS/Linux 激活：`source .venv/bin/activate`。
如果 PowerShell 不允许激活，直接用 `.venv\Scripts\python.exe` 替换下方的 `python` 即可。

```bash
python -m pip install --upgrade pip
python -m pip install ".[model]"
```

首次识别会通过 RightWayUp 从 Hugging Face 下载权重，因此第一次调用较慢，且需要能够访问 Hugging Face。
后续使用本机缓存。**Git 仓库不附带模型权重**。不需要 OpenAI API、API 密钥或 PyTorch。

也可以直接从 GitHub 安装，不手动克隆：

```bash
python -m pip install "spincap[model] @ git+https://github.com/JonyQY/spincap.git"
```

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

需要批量处理图片时，可用 `default_readers()` 初始化一次并将实例复用于 `build_solver`，
避免逐张调用便利函数时重新构造模型。

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
- RightWayUp 的 `pico/nano/fast` 使用 ViT-S/14，`max` 使用 ViT-L/14。
  各档读数不能视为统计独立；一致也可能同时出错。
- 本项目没有自行训练方向识别模型，不提供通用成功率保证。无明确朝向的图片可能无法识别。
- `read_angle` 的默认门控基于角度一致性及接缝；它不额外按模型的 `abstain` 标志过滤。
- 缺依赖、下载失败会抛出初始化异常；`read_all` 会报告各档预测错误，`read_angle` 在预测失败时返回 `None`。
- 多次读取同一图片的固定模型，不能当作多个独立来源重复投票。

离线预下载请遵循 RightWayUp 的模型目录约定，将完整模型目录通过
`RIGHTWAYUP_MODEL_DIR` 环境变量指定。上游文件说明见
[RightWayUp 模型仓库](https://huggingface.co/ortusai/rightwayup)。

## 许可与来源

spincap 代码使用 [MIT](LICENSE) 许可证。
RightWayUp 代码与权重使用其上游 Apache-2.0 许可证；详见
[第三方组件说明](THIRD_PARTY_NOTICES.md)。本仓库仅发布独立求解模块、示例和测试。
