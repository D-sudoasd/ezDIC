# ezDIC v0.1.4

发布日期：2026-08-30

本文件描述 main/source 的 v0.1.4 release-ready 状态；本轮未创建 tag、GitHub release 或 portable ZIP。未来单独创建 tag/release 后，才可提供对应的 v0.1.4 Windows ZIP。

## 本轮变化

- 明确并统一双模式工作流：虚拟引伸计用于两 ROI 标记的一维应变历史；全场模式用于矩形 ROI 内的面内 2D DIC。
- 全场模式以所选分析范围的第一帧作为固定参考帧，对后续变形帧建立 POI 网格并使用 IC-GN 或 IC-LM 计算位移/应变。
- 全场核心结果固定写入 `dic/`：每个有有限应变场的变形帧都有 TXT/CSV 表、`u`、`v`、`Exx`、`Eyy`、`Exy` 图和 `frame_####_parameters.txt` provenance；无有效/有限应变的失败帧不作为成功结果导出，`Exx` 图像 overlay 为可选的附加 QC 输出。
- 每个 parameters 文件记录固定 reference frame/filename、当前 frame/filename、ROI、图像尺寸、实际 subset/step/window/solver、阈值和平滑设置等可追溯上下文。
- 全场预检要求至少 3 × 3 POI；过窄 ROI 或参数组合无法形成三行三列 POI 时会被阻止。重复运行时已有 `frame_####*` 结果会保留性移动到 `dic/_previous_runs/<timestamp>/` 后再写本轮结果。
- 全场输出采用事务式提交：本轮先写 staging，正常完成后才把当前候选结果提交到 `dic/` 根目录；若致命 I/O、求解或导出异常中断，已产生的 partial 文件保留性移动到 `dic/_failed_runs/<timestamp>/`，不冒充当前成功结果。
- 无有限应变的帧是正常跳过的失败帧；其他帧有效且整轮无致命异常时仍可提交。整轮没有有效帧时失败，不提交当前结果。
- 全场 UI 提供可见的可选 Exx overlay 开关；1D 导出项不参与 2D 核心输出，也不作为 2D 运行门槛。
- 在 README、中文使用说明、引用/归档元数据和便携包清单中同步版本、发布日期、双模式说明和科学边界；既有历史发布说明保留不变。
- 将可选 `originpro` 依赖移至 `requirements-origin.txt`；发布构建依赖仍显式包含它，以保留可选 OPJU 打包路径。
- 发布构建脚本增加版本、JSON/引用元数据、spec 数据清单和原生命令退出码检查，并把 LICENSE/CITATION 文件复制到便携包。

历史兼容说明：Poisson ratio export and GUI workflow update 仍以保留的历史发布说明为准；本版本保留该能力，不把历史变化重复计算为 v0.1.4 的新科学结论。

## 全场结果边界

- `x`、`y`、`u`、`v` 的单位是 px；所有应变分量无量纲。
- `Exy`/`exy` 是应变张量剪切分量，不是额外乘以 2 的工程剪切量。
- 输出是 POI 网格，不是逐像素结果；该模式是面内 2D DIC，不是立体/3D DIC 或 DVC。
- 相关失败点的数值结果保持 `NaN`，不插值填补。没有有限应变场的帧视为失败，不作为成功帧导出；整个运行没有有效应变点时失败，不报告为完成。
- 便携包和图像输出是工程交付物。它们不构成代表性实验数据、标定、误差/不确定度评定或材料科学定量认可。

## How to cite

Gong, D. (2026). ezDIC: A lightweight virtual extensometer for extracting linear strain from image sequences (Version 0.1.4) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.20222465
