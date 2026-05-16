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
  engineering_strain_G01.png
  engineering_strain_all_groups.png
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

Optional exports include full CSV tables, correlation plots, tracking overlays, and parameter summaries.

## Windows Quick Start

1. Download `ezDIC_Windows_x64_v0.1.2.zip` from the release package.
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
  ezDIC_Windows_x64_v0.1.2.zip
```

## Validation

The current automated checks cover:

- Origin-compatible TXT export.
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
Gong, D. (2026). ezDIC: A lightweight virtual extensometer for extracting linear strain from image sequences (Version 0.1.2) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.20222465
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
