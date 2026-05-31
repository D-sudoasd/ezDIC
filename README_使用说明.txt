ezDIC v0.1.3 使用说明
======================

Developer
---------
ezDIC was developed by Dr. Delun Gong.

DOI
---
10.5281/zenodo.20222465
https://doi.org/10.5281/zenodo.20222465

System Requirements
-------------------
- Windows 10/11 x64.
- Python is not required on the user's computer.
- Administrator permission is not required for normal use.

How To Run
----------
1. Extract the full ezDIC_Windows_x64 folder from the zip package.
2. Open the extracted folder.
3. Double-click ezDIC.exe.

Important
---------
Do not copy ezDIC.exe alone. The _internal folder and the notice/version files must stay with ezDIC.exe.

Basic Workflow
--------------
1. Select the image folder.
2. Select or confirm the output folder.
3. Load the image sequence.
4. Set the start and end frames.
5. Select strain direction and tracking mode.
6. Draw ROI 1 and ROI 2, then add the ROI group.
7. Optional: set axial/transverse roles for Poisson-ratio export. Multiple groups with the same role and direction are averaged frame by frame.
8. Click Start Analysis and Export.

Default Output
--------------
By default, ezDIC exports:
- Origin-compatible TXT files with Frame, EngineeringStrain, and TrueStrain.
- Mean-strain TXT files for repeated extensometers with the same role and direction.
- Poisson-ratio TXT/PNG files when axial/transverse ROI roles are set.
- Engineering strain PNG plots.
- QC summary TXT.

Optional outputs such as an Origin OPJU project, full CSV files, correlation plots, overlays, and parameter summaries are disabled by default and can be enabled in the export options.

Publication Figure Package
--------------------------
The optional publication-style figure package exports PNG/TIFF/PDF/SVG/EPS files: high-resolution PNG/TIFF bitmaps and PDF/SVG/EPS vector figures.

Output folder:
- optional/publication_figures

Use this package when you need manuscript or figure-layout drafts with consistent fonts, line widths, markers, legend sizing, and tight bounding boxes. These figures do not replace the core TXT/CSV data exports; they are an additional plotting output for papers, reports, and presentations.

Mean Strain Export / 平均应变导出
--------------------------------
勾选 Origin TXT（三列核心数据）后，平均应变会随核心结果一起导出，不需要单独勾选其他选项。

平均应变文件位置：
- core/strain_mean_groups.txt

同时，平均应变列也会追加到：
- core/strain_all_groups.txt

列名规则：
- MeanEngineeringStrain_<role>_<mode>
- MeanTrueStrain_<role>_<mode>
- StdEngineeringStrain_<role>_<mode>
- SemEngineeringStrain_<role>_<mode>
- ValidGroupCount_<role>_<mode>

注意：程序只会把相同 role 和相同 actual_mode 的 ROI 组逐帧求平均。例如，两条普通纵向引伸计会合成 MeanEngineeringStrain_none_y；如果一条是 y、一条是 x，或者一条 role 是 axial、另一条是 none，就不会合成同一条平均曲线。

处理完成后，ezDIC 会自动打开输出根目录。该目录下通常包含 core、qc 和 optional 子目录。

Origin OPJU Export
------------------
The Origin OPJU option writes the core result tables directly into ezDIC_results.opju. It requires Windows, OriginPro 2021+, a valid local OriginPro license, and the originpro Python package. If OriginPro or originpro is unavailable, ezDIC keeps the TXT/PNG/CSV results and reports only the OPJU export failure.

Attribution And Usage Notice
----------------------------
This software was developed by Dr. Delun Gong for lightweight extraction of linear strain from image sequences.

Recommended citation:
Gong, D. (2026). ezDIC: A lightweight virtual extensometer for extracting linear strain from image sequences (Version 0.1.3) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.20222465

Users are not permitted to:
1. claim that they developed this software;
2. remove or alter the developer attribution;
3. redistribute, copy, forward, or share this software with unauthorized users;
4. use this software outside the authorized research or teaching context.

If you need to share or reuse this software, please obtain permission from Dr. Delun Gong first.

If you use ezDIC in a thesis, paper, presentation, or report, please cite the DOI above.

Security Notice
---------------
This first release is not code-signed. Windows Defender or SmartScreen may show an unknown publisher warning on some computers.
