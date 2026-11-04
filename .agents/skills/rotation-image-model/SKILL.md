---
name: rotation-image-model
description: 调用旋转图片算法模型读取本地图片偏角、计算旋转滑块位移，或将求解器接入 Python/Agent 程序。用于旋转图片、图片转正角度和旋转验证码；不处理拼图缺口、文字识别或点选题。
---

# 旋转图片算法模型

使用现成的 `spincap` Python API 或 JSON 命令行执行识别，不凭目测生成算法结果。

## 确认输入和运行环境

- 获取本次图片的本地绝对路径，确认文件实际存在。支持模型可读取的 PNG/JPEG 等图片。
- 只求角度时无需轨道参数。只有调用方提供或已标定 `pixels_per_turn` 和方向时，才计算滑块位移。
- 优先使用开发者指定的 Python 环境；后续安装和执行始终使用同一个解释器。
- 技能位于仓库内时，从技能文件向上寻找同时含 `pyproject.toml` 与 `spincap/` 的仓库根目录。技能单独复制到其他项目时，先检查当前环境能否 `import spincap`；不能时在工作区克隆下述仓库，勿把技能文件所在目录误当成模型目录。

## 首次准备

已经可用时跳过安装。未克隆时执行：

```bash
git lfs install
git clone https://github.com/JonyQY/rotation-image-model.git
cd rotation-image-model
git lfs pull
python -m venv .venv
```

需要 Python 3.10+、Git LFS 和本仓库的访问权限。仓库私密时，使用开发者已有的 GitHub 登录流程；不要把密钥写进命令、技能或返回结果。

在仓库根目录安装模型依赖：

```powershell
# Windows PowerShell，无需激活虚拟环境
.venv\Scripts\python.exe -m pip install ".[model]"
```

```bash
# macOS / Linux
.venv/bin/python -m pip install '.[model]'
```

下文 `python` 表示已选定的解释器；在脚本或工具参数中替换成它的实际路径。
权重由 Git LFS 随仓库拉取，约 384 MB。最大模型首次使用会在用户缓存中合并分片并校验；后续推理使用本地文件。

## 首选：返回 JSON 的单次调用

```bash
python -m spincap "/absolute/path/puzzle.png"
```

结果形如 `{"angle_cw":270.55,"usable":true}`。`angle_cw` 是图片内容偏离正立方向的**顺时针角度**，范围 `[0,360)`；要转正图片应逆时针旋转该角度。

已确认轨道参数时：

```bash
python -m spincap "/absolute/path/puzzle.png" --pixels-per-turn 240 --complement
```

`240` 仅为演示值。`complement=False` 对应 `angle/360*pixels_per_turn`，`--complement` 对应补角；两者均按一圈归一化。依据当前控件方向选择，不能从角度本身猜方向。输出中的 `offset_px` 才是拖动像素数，不能把角度直接当像素。

读取退出码和输出：

| 情况 | 处理 |
| --- | --- |
| `0` 且 JSON 中 `usable:true` | 返回实际 `angle_cw`，如果输出含 `offset_px` 一并返回。 |
| `2` 且 JSON 中 `usable:false` / `angle_cw:null` | 报告当前图片未通过筛选；停止本次求解，交由调用方换图或人工处理。 |
| `2` 且 stderr 为参数/文件错误，无 JSON | 修正文件路径或参数；不要误报为模型分歧。 |
| `1` | 检查 stderr 中的依赖、权重或初始化错误；未得到结果时不编造角度。 |

默认模式会核对四档读数，并拒绝接近零度接缝或分歧过大的图片。
`--all` 用于诊断，列出的原始读数不是共识结果。`--tier fast` 等单档模式跳过默认筛选，只在调用方明确选择该模式时使用；不要为了获得数字而静默降级。

## Python 接入

```python
from spincap import read_angle, offset_for

angle = read_angle(image_path)
if angle is None:
    result = {"usable": False, "angle_cw": None}
else:
    result = {"usable": True, "angle_cw": angle}
    # 仅当这两个值已经按当前控件标定时计算：
    # result["offset_px"] = offset_for(angle, pixels_per_turn, complement=use_complement)
```

批量图片时复用读图器实例，避免逐张初始化四档模型：先 `default_readers()`，再用 `build_solver(readers, baseline='max', ...)` 配置回调。此处 `baseline='max'` 按档位映射到实际读图器名称，不假定 `read_all` 的来源键名。

需要接入自动化流程时，按仓库 README 的回调接口或 `examples/offline_demo.py` 实现当前题图读取、换图、拖动和 `verify`。示例的模拟成功不能当作网站通过证据。算法 `usable:true` 表示读数通过筛选；只有实际页面/业务结果验证成功才能报告验证码已通过。仅识别图片的请求不扩展为登录、操作网站或自动刷新。

## 常见恢复

- 缺少 `spincap` 或模型依赖：在确认的仓库根目录，用同一解释器安装 `.[model]`。
- 权重缺失或只下载了 LFS 指针：在模型仓库运行 `git lfs pull`，然后用同一解释器执行 `python -m pip install --force-reinstall --no-deps .`，更新已安装包中的权重。
- 缓存无写入权限：将 `SPINCAP_CACHE_DIR` 指向调用方允许写入的目录。`SPINCAP_MODEL_DIR` 可指定另一个包含完整权重/分片及 manifest 的本地模型目录。
- 校验失败：重新拉取并核对权重，保留完整性校验；不要把损坏文件交给推理引擎。

最终报告实际使用的图片、模式、角度、可选位移及是否得到可用结果。没有执行时明确说明；不要把算法结果说成已通过第三方站点验证。
