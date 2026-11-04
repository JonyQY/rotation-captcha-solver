# Agent 入口

需要识别旋转图片角度、求旋转滑块位移或集成求解器时，读取
[rotation-image-model 技能](.agents/skills/rotation-image-model/SKILL.md)，使用现有 `spincap` API/CLI。
该技能也支持单独安装到其他项目的技能目录，安装及调用说明见 README 的「Agent 调用」。

修改算法或接口时保留「角度、像素位移、页面验证结果」的区分；默认筛选失败不降级为成功。
权重与分片由 Git LFS 管理，保持 manifest 校验。新增的实际行为变更按需验证，
离线模拟示例只能证明回调组合，不能证明真实网站通过率。
