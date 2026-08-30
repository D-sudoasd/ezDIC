ezDIC v0.1.4 使用说明
======================
发布日期：2026-08-30
当前身份：main/source version 0.1.4（release-ready source）。本源代码快照尚未创建 v0.1.4 tag、GitHub release 或便携 ZIP；只有未来单独创建 tag/release 后才会有对应的 v0.1.4 Windows ZIP。

定位与开发者
------------
ezDIC 由 Dr. Delun Gong 开发，是一个面向图像序列的双模式应变工作站：

1. 虚拟引伸计：追踪两组用户定义的 ROI 标记，导出一维工程应变、真应变和 QC。
2. 全场 2D DIC：在矩形 ROI 内建立 POI（point of interest）网格，用 IC-GN 或 IC-LM 计算面内位移与应变场。

全场模式是面内、局部子集的 2D DIC。它不是逐像素 DIC、立体/3D DIC、DVC，也不是全局有限元 DIC。

DOI
---
10.5281/zenodo.20222465
https://doi.org/10.5281/zenodo.20222465

系统要求
--------
- Windows 10/11 x64。
- 便携版用户不需要在电脑上安装 Python。
- 正常运行不需要管理员权限。

如何运行便携版
--------------
1. 打开 [Releases 页面](https://github.com/D-sudoasd/ezDIC/releases)，下载页面当前实际列出的 Windows x64 版本。当前源代码快照不提供 v0.1.4 ZIP；未来只有单独创建 v0.1.4 tag/release 后才可下载该 ZIP。
2. 解压完整的已下载文件夹；便携包内的顶层目录名是 `ezDIC_Windows_x64`，版本号只出现在 ZIP 文件名中。
3. 双击 ezDIC.exe。

重要：不要只复制 ezDIC.exe。`_internal` 文件夹以及 LICENSE.txt、CITATION.cff、VERSION.txt 和 NOTICE_Attribution_and_Usage.txt 必须与 ezDIC.exe 一起保留。 Do not copy ezDIC.exe alone.

源代码运行、测试与构建
----------------------
源代码运行需要基础依赖；测试和 Windows 发布构建使用包含基础依赖、测试工具、PyInstaller 以及发布所需可选 OriginPro 依赖的构建集合：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m pytest -q
```

构建便携包：

```powershell
powershell -File .\build_release.ps1
```

Origin OPJU 是可选功能。若只需要基础运行/测试，不必安装 OriginPro；启用 OPJU 时，在 Windows + OriginPro 2021+、有效本地许可证条件下安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-origin.txt
```

基础依赖中不包含 `originpro`。如果 OriginPro 或该 Python 包不可用，TXT/PNG/CSV 等已有结果仍可保留，OPJU 导出会单独报告失败。

通用工作流
----------
1. 选择图像文件夹。
2. 选择或确认输出文件夹。
3. 加载图像序列。
4. 设置起始帧和结束帧。
5. 根据当前模式完成下列步骤。
6. 点击“开始分析并导出结果”。

虚拟引伸计模式
--------------
1. 选择应变方向和追踪模式。
2. 在参考帧绘制 ROI 1 和 ROI 2，然后添加 ROI 组。
3. 可选：为 ROI 组设置 axial（拉伸方向）/ transverse（横向方向）角色以导出泊松比。同一角色和实际方向的多组会逐帧求平均。
4. 检查预检信息后开始分析。

该模式的核心结果写入 `core/`，质量控制摘要写入 `qc/`；可选的完整 CSV、相关系数图、追踪 overlay、参数和论文图包写入 `optional/`。

全场 2D DIC 模式
----------------
1. 切换工作区模式到“全场 2D DIC”。
2. 在当前分析范围的第一帧（固定参考帧）绘制一个矩形 field ROI。
3. 设置 subset 尺寸、POI 步长以及 IC-GN 或 IC-LM 求解器。
4. 开始分析。每个后续变形帧都与同一个固定参考帧相关，不会静默改成逐帧参考。

所选全场分析范围内的图像尺寸必须一致；尺寸不一致会在预检/处理时失败。

全场输出采用事务式流程：本轮候选文件先写入 staging 临时区，只有整轮正常完成后才提交到输出根目录的 `dic/`，提交前才成为当前结果。新轮计算开始前，旧的成功 `frame_####*` 结果会保留性移动到 `dic/_previous_runs/<timestamp>/`。

全场结果固定写入输出根目录下的 `dic/`；对有有限应变场的变形帧，不依赖“任选导出项”即可得到核心数据。没有有限应变场的帧属于**正常跳过的失败帧**：它不生成本轮当前帧文件，但只要其他帧有效且没有致命异常，其他有效帧仍可提交：

```text
dic/
├─ frame_0002.txt       # x, y, u, v, zncc, valid, Exx, Eyy, Exy, exx, eyy, exy
├─ frame_0002.csv
├─ frame_0002_u.png
├─ frame_0002_v.png
├─ frame_0002_Exx.png
├─ frame_0002_Eyy.png
├─ frame_0002_Exy.png
└─ frame_0002_parameters.txt
```

每个有效变形帧的 `frame_####_parameters.txt` 都是固定的 provenance 记录，至少说明：固定 `reference_frame_1based` 与 `reference_filename`、当前 `frame_global_1based` 与 `frame_filename`、`field_roi`、图像尺寸，以及实际生效的 `subset_size_px`、`step_px`、`strain_window`、`solver`、`zncc_min` 和平滑参数；若可用，还记录图像序列 fingerprint。

如果重复运行时 `dic/` 中已经存在匹配的 `frame_####*` 结果，旧结果会保留性移动到 `dic/_previous_runs/<timestamp>/`，再写入本轮结果，避免把不同运行的同名帧混在一起。

字段和科学边界
--------------
- `u`/`v`/`x`/`y` 均以 **px** 记录；其中 `x`、`y` 是 POI 坐标，`u`、`v` 是位移。
- `Exx`、`Eyy`、`Exy` 是 Green-Lagrange 应变；`exx`、`eyy`、`exy` 是无穷小应变；应变均为**无量纲**。
- `Exy`/`exy` 是应变张量的非对角剪切分量，不是额外乘以 2 的工程剪切量。
- 输出是矩形 ROI 内的 POI 网格，不是每个图像像素的结果，也不提供 3D/DVC 信息。
- `valid` 标记 POI 是否通过相关质量阈值。失败点的数值字段保持 `NaN`，不插值、不用邻点填补。
- 没有有限应变场的变形帧视为正常跳过的失败帧；如果整个全场分析没有有效应变点，运行失败，不报告为“完成”。
- 若中途发生致命的 I/O、求解或导出异常，本轮 staging 中已经产生的 partial 文件会保留性移动到 `dic/_failed_runs/<timestamp>/`，不会作为当前成功结果留在 `dic/` 根目录；整轮报告失败且不提交 partial 结果。
- 预检要求至少形成 **3 × 3 POI 网格**；ROI 过窄、subset/step 组合无法形成三行三列 POI 时会在开始前阻止处理。
- 全场 UI 有一个可见的可选 **Exx overlay** 开关。开启后会在分析图像上叠加 Exx 色图，并保存为 `frame_NNNN_overlay.png`；它只是可视化 QC，不替代固定核心表格和应变图。
- 1D 导出项在全场模式下不参与 2D 核心输出，也不会成为 2D 分析的开始条件。

默认输出
--------
- Origin-compatible TXT：`Frame`、`EngineeringStrain`、`TrueStrain`。
- 同一角色和实际方向的重复引伸计平均应变 TXT。
- 设置 axial/transverse 角色后生成泊松比 TXT/PNG。
- 工程应变 PNG 图。
- QC 摘要 TXT。

一维应变定义：

```text
engineering strain = (L - L0) / L0
true strain        = ln(L / L0)
PoissonRatio       = - ε_transverse / ε_axial   (engineering)
```

追踪失败帧、缺失应变值和过小轴向应变对应的结果保留为 `NaN`，不静默插值。

论文图包
--------
启用论文图包后，会在 `optional/publication_figures` 导出 PNG/TIFF/PDF/SVG/EPS。该图包只增加统一样式的图，不替代核心 TXT/CSV 数据或 QC 证据。

推荐引用
--------
Gong, D. (2026). ezDIC: A lightweight virtual extensometer for extracting linear strain from image sequences (Version 0.1.4) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.20222465

归属与使用限制
--------------
用户不得：
1. 声称该软件由其开发；
2. 删除或修改开发者署名；
3. 向未经授权的用户重新分发、复制、转发或分享该软件；
4. 在获授权的科研或教学范围之外使用该软件。

如需分享、复用、修改或重新分发，请先联系 Dr. Delun Gong 获得许可。论文、学位论文、报告或演示文稿使用 ezDIC 时，请引用上述 DOI。具体条款见 LICENSE.txt 与 NOTICE_Attribution_and_Usage.txt。

安全提示
--------
当前版本未进行代码签名。部分电脑上的 Windows Defender 或 SmartScreen 可能显示“未知发布者”警告。
