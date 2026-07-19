<p align="center">
  <img src="assets/readme/hero.svg" width="100%" alt="ezDIC: lightweight virtual extensometer for linear strain from image sequences.">
</p>

# ezDIC

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20222465.svg)](https://doi.org/10.5281/zenodo.20222465)

**A lightweight virtual extensometer for extracting linear strain from image sequences.**

ezDIC tracks two user-defined ROI markers across an image sequence and exports engineering strain, true strain, quality-control information, and Origin-compatible TXT (optional OPJU). It is for researchers who need a reliable **1D strain history** without running full-field DIC.

Developed by **Dr. Delun Gong** · DOI [10.5281/zenodo.20222465](https://doi.org/10.5281/zenodo.20222465)

## Why ezDIC

Many materials experiments only need a linear strain curve — not displacement fields or strain maps.

| You need | ezDIC provides |
| --- | --- |
| Fast 1D strain | Two-ROI virtual extensometer |
| Honest failed frames | `NaN` instead of silent interpolation |
| Lab plotting | Origin-compatible TXT; optional OPJU |
| Multiple gauges | Mean strain ± SD / SEM; Poisson-ratio roles |
| No Python for users | Portable Windows folder with `ezDIC.exe` |

## Typical use cases

- Tensile, compression, bending, or thermal-deformation sequences where the target is a linear strain curve
- Quick cross-check of physical extensometers or full-field DIC
- Teaching image-based strain without a commercial DIC package
- Exploratory analysis before committing to full-field DIC

## Workflow

```text
Load images  →  Draw two ROIs  →  Track  →  Export strain + QC
```

## Outputs

Default `core/` result folder:

```text
core/
  strain_G01.txt
  strain_all_groups.txt
  strain_mean_groups.txt
  ezDIC_results.opju       # optional; OriginPro 2021+ + originpro
  poisson_ratio.txt        # when axial/transverse roles are set
  engineering_strain_*.png
qc/
  qc_summary.txt
optional/
  publication_figures/     # PNG/TIFF/PDF/SVG/EPS when enabled
```

Primary TXT shape:

```text
Frame	EngineeringStrain	TrueStrain
1	0.00000000	0.00000000
2	-0.00000254	-0.00000254
```

- **Mean strain**: averages groups with the same `role` and `actual_mode`; rejected / `NaN` frames excluded.
- **Poisson ratio**: define at least one `axial` and one `transverse` ROI group; ratio from engineering strain, with `NaN` when axial magnitude is tiny or missing.
- **OPJU**: requires Windows, OriginPro 2021+, a valid local license, and `originpro`. If OPJU fails, TXT/PNG/CSV and publication figures are kept.

## Windows quick start

1. Download `ezDIC_Windows_x64_v0.1.3.zip` from the [releases](https://github.com/D-sudoasd/ezDIC/releases).
2. Extract the full `ezDIC_Windows_x64` folder.
3. Double-click `ezDIC.exe`.
4. Keep `_internal/` next to the EXE — do not copy `ezDIC.exe` alone.

Target platform: **Windows 10/11 x64**.

## Run from source

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe dic_virtual_extensometer_gui_v7_multi_roi_range.py
```

## Build the Windows release

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1
```

```text
release/
  ezDIC_Windows_x64/
  ezDIC_Windows_x64_v0.1.3.zip
```

## Validation

```powershell
py -m pytest -q
```

Automated checks cover Origin TXT export, OPJU table construction with a fake Origin API, true-strain recomputation, QC summary, GUI attribution, and packaging metadata.

## Scientific notes

```text
engineering strain = (L - L0) / L0
true strain        = ln(L / L0) = ln(1 + engineering strain)
```

`L0` is the initial ROI-center separation; `L` is the current separation. Failed tracking frames stay `NaN`.

Poisson ratio (engineering strain):

```text
PoissonRatio = - TransverseEngineeringStrain / AxialEngineeringStrain
```

`NaN` when a role is missing, mean strain is `NaN`, or `abs(AxialEngineeringStrain) < 1e-6`.

## Limitations

ezDIC is **not** full-field DIC. It does not compute strain maps, displacement fields, or local heterogeneity. Use it when a virtual extensometer is scientifically appropriate.

## How to cite

```text
Gong, D. (2026). ezDIC: A lightweight virtual extensometer for extracting linear strain
from image sequences (Version 0.1.3) [Computer software]. Zenodo.
https://doi.org/10.5281/zenodo.20222465
```

`CITATION.cff` is included so GitHub shows **Cite this repository**.

## Attribution and usage

Developed by **Dr. Delun Gong**. Users are not permitted to:

1. claim they developed this software;
2. remove or alter developer attribution;
3. redistribute or share with unauthorized users;
4. use it outside authorized research or teaching context.

Obtain permission from the author before sharing or reusing beyond that scope. See also `NOTICE_Attribution_and_Usage.txt` and `LICENSE.txt` in the repository.
