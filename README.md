# ezDIC

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20222465.svg)](https://doi.org/10.5281/zenodo.20222465)

**A lightweight virtual extensometer for extracting linear strain from image sequences.**

ezDIC is designed for researchers who need fast, practical strain extraction without running a full-field Digital image correlation workflow. It tracks two user-defined ROI markers across an image sequence and exports engineering strain, true strain, quality-control information, and Origin-compatible TXT files for plotting and reporting.

Developed by **Dr. Delun Gong**.

DOI: [10.5281/zenodo.20222465](https://doi.org/10.5281/zenodo.20222465)

## Why ezDIC?

Many materials experiments only require a reliable 1D strain history rather than full-field displacement maps. ezDIC focuses on that narrower problem:

- **Simple workflow**: load images, draw two ROIs, run tracking, export strain.
- **Virtual extensometer model**: strain is computed from the changing distance between two tracked ROI centers.
- **Origin-compatible TXT output**: the default export contains `Frame`, `EngineeringStrain`, and `TrueStrain`.
- **Origin OPJU export**: optionally writes core result tables directly into an OriginPro project file.
- **Mean-strain export**: multiple extensometers with the same role and direction are averaged frame by frame with standard deviation, SEM, and valid-count columns.
- **Poisson-ratio export**: mark axial and transverse ROI groups to export transverse strain and `PoissonRatio`; multiple groups are averaged before the ratio is computed.
- **Quality control built in**: rejected frames, adaptive accepts, correlation scores, and QC summaries are reported.
- **No Python required for users**: Windows releases are distributed as a green, portable folder with `ezDIC.exe`.
- **Research-oriented defaults**: failed tracking frames remain `NaN` instead of being silently interpolated.

## Typical Use Cases

- Tensile, compression, bending, or thermal-deformation image sequences where the primary target is a linear strain curve.
- Quick validation of extensometer or DIC measurements.
- Teaching image-based strain extraction without requiring a full commercial DIC package.
- Lightweight exploratory analysis before committing to full-field DIC.

## Outputs

By default, ezDIC writes a compact `core/` result folder:

```text
core/
  strain_G01.txt
  strain_all_groups.txt
  strain_mean_groups.txt
  ezDIC_results.opju       # optional, requires OriginPro 2021+ and originpro
  poisson_ratio.txt        # when axial/transverse ROI roles are set
  engineering_strain_G01.png
  engineering_strain_all_groups.png
  poisson_ratio.png        # when axial/transverse ROI roles are set
qc/
  qc_summary.txt
```

The primary TXT format is intentionally simple:

```text
Frame	EngineeringStrain	TrueStrain
1	0.00000000	0.00000000
2	-0.00000254	-0.00000254
3	0.00000580	0.00000580
```

Optional exports include an Origin OPJU project, full CSV tables, correlation plots, tracking overlays, and parameter summaries. The OPJU export requires Windows, OriginPro 2021+, a valid local OriginPro license, and the `originpro` Python package. It writes worksheet data only; publication figures still come from the existing PNG exports or from manual plotting in OriginPro.

For repeated virtual extensometers, `strain_mean_groups.txt` averages groups with the same `role` and `actual_mode` frame by frame. Rejected frames and `NaN` strain values are excluded from the mean. The mean table includes:

```text
MeanEngineeringStrain_<role>_<mode>	MeanTrueStrain_<role>_<mode>	StdEngineeringStrain_<role>_<mode>	SemEngineeringStrain_<role>_<mode>	ValidGroupCount_<role>_<mode>
```

For Poisson-ratio analysis, add at least one ROI group with role `axial` and at least one with role `transverse`. `strain_all_groups.txt` keeps the original per-group columns, appends mean-strain columns, and appends:

```text
AxialEngineeringStrain	TransverseEngineeringStrain	PoissonRatio
```

## Windows Quick Start

1. Download `ezDIC_Windows_x64_v0.1.3.zip` from the release package.
2. Extract the full `ezDIC_Windows_x64` folder.
3. Double-click `ezDIC.exe`.
4. Do not copy `ezDIC.exe` alone; keep `_internal/` in the same folder.

Target platform: **Windows 10/11 x64**.

## Running From Source

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe dic_virtual_extensometer_gui_v7_multi_roi_range.py
```

## Building The Windows Release

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1
```

The script creates:

```text
release/
  ezDIC_Windows_x64/
  ezDIC_Windows_x64_v0.1.3.zip
```

## Validation

The current automated checks cover:

- Origin-compatible TXT export.
- Origin OPJU table construction and failure handling with a fake OriginPro API.
- true strain recomputation from engineering strain.
- QC summary generation.
- GUI title and developer attribution.
- release metadata and PyInstaller packaging files.

Run:

```powershell
py -m pytest -q
```

## How to Cite

This repository includes `CITATION.cff`, so GitHub will show a **Cite this repository** link on the project page. For papers, theses, reports, and presentations, please cite the Zenodo DOI:

```text
Gong, D. (2026). ezDIC: A lightweight virtual extensometer for extracting linear strain from image sequences (Version 0.1.3) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.20222465
```

```text
DOI: 10.5281/zenodo.20222465
```

GitHub repository: <https://github.com/D-sudoasd/ezDIC>

## Scientific Notes

ezDIC computes engineering strain using:

```text
engineering strain = (L - L0) / L0
```

and true strain using:

```text
true strain = ln(L / L0) = ln(1 + engineering strain)
```

where `L0` is the initial ROI-center separation and `L` is the current separation. If tracking fails, the frame is exported as `NaN` to preserve the experimental record.

Poisson ratio is computed from engineering strain. If more than one axial or transverse ROI group is defined, ezDIC first computes the frame-by-frame mean strain within each role:

```text
PoissonRatio = - TransverseEngineeringStrain / AxialEngineeringStrain
```

If either role has no valid strain for a frame, either mean strain is `NaN`, or `abs(AxialEngineeringStrain) < 1e-6`, the Poisson-ratio value is exported as `NaN`.

## Limitations

ezDIC is not a replacement for full-field DIC. It does not compute strain maps, displacement fields, or local strain heterogeneity. It is intended for fast extraction of a representative linear strain curve from image sequences where a virtual extensometer is scientifically appropriate.

## Attribution And Usage

This software was developed by **Dr. Delun Gong** for lightweight extraction of linear strain from image sequences.

DOI: [10.5281/zenodo.20222465](https://doi.org/10.5281/zenodo.20222465)

Users are not permitted to:

1. claim that they developed this software;
2. remove or alter the developer attribution;
3. redistribute, copy, forward, or share this software with unauthorized users;
4. use this software outside the authorized research or teaching context.

If you need to share or reuse this software, please obtain permission from **Dr. Delun Gong** first.

## Keywords

Digital image correlation, virtual extensometer, strain extraction, engineering strain, true strain, materials testing, tensile testing, image sequence analysis, Origin-compatible TXT.
