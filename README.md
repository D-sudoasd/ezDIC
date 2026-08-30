<p align="center">
  <img src="assets/readme/hero.svg" width="100%" alt="ezDIC: dual-mode 1D strain and in-plane full-field 2D DIC for image sequences.">
</p>

# ezDIC

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20222465.svg)](https://doi.org/10.5281/zenodo.20222465)

**A lightweight dual-mode strain workstation for image sequences.**

Main/source version: **0.1.4** · release-ready source · 2026-08-30

This source snapshot has no v0.1.4 tag, GitHub release, or portable ZIP. A v0.1.4 Windows ZIP can be downloaded only after a separate tag/release is created.

ezDIC has two explicit workflows:

1. **Virtual extensometer:** track two user-defined ROI markers and export engineering strain, true strain, QC, and Origin-compatible TXT (optional OPJU).
2. **Full-field 2D DIC:** correlate a rectangular ROI on a fixed reference frame with IC-GN or IC-LM, sample a POI grid, and export displacement and strain maps.

The full-field DIC workflow is an in-plane, local-subset 2D method. It does not replace stereo/3D DIC, DVC, or a global finite-element DIC system.

Developed by **Dr. Delun Gong** · [DOI 10.5281/zenodo.20222465](https://doi.org/10.5281/zenodo.20222465)

<p align="center">
  <img src="assets/readme/section-01-why.svg" width="100%" alt="01 Modes: virtual extensometer strain histories and full-field 2D maps.">
</p>

| You need | ezDIC provides |
| --- | --- |
| Fast 1D strain | Two-ROI virtual extensometer |
| In-plane full-field maps | Rectangular ROI, POI grid, IC-GN / IC-LM, `u`/`v` and strain components |
| A fixed comparison frame | Every full-field deformation frame is correlated to the selected reference frame |
| Honest failures | Failed points/frames remain `NaN`; a full-field run with zero valid strain points fails |
| Lab plotting | Origin-compatible TXT; optional OPJU; publication colormaps |
| Multiple gauges | Mean ± SD / SEM; Poisson-ratio roles |
| No Python for users | Portable Windows folder with `ezDIC.exe` |

```text
Virtual extensometer:  Load images → draw ROI 1 + ROI 2 → track → core/ + qc/
Full-field 2D DIC:    Load images → draw field ROI → IC-GN/IC-LM → dic/
```

## Full-field output contract

Full-field analysis uses the first frame in the selected analysis range as one fixed reference. Each later frame is correlated to that same reference; the workflow does not silently switch to a frame-to-frame reference. The rectangular ROI is sampled at points of interest (POIs), so the result is a POI grid rather than a value at every image pixel. It is not a 3D measurement.

All images in the selected full-field range must have the same dimensions; a mismatch is a validation failure.

Full-field output is transactional. A new run first writes its candidate files to a staging area. Only after the whole run completes normally are those files committed to the `dic/` root as the current result. Before the new run starts, old successful `frame_####*` files are retention-moved to `dic/_previous_runs/<timestamp>/`.

The core output is fixed and is written under `dic/` for every analyzed deformation frame with a finite strain field. A failed frame is not exported as a successful result:

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

`x`, `y`, `u`, and `v` are in **px**. All strain components are **dimensionless**. `Exx`, `Eyy`, and `Exy` are Green–Lagrange components; `exx`, `eyy`, and `exy` are infinitesimal components. `Exy`/`exy` are **tensor shear components** (the off-diagonal strain terms), not engineering shear values with an extra factor of two.

The `valid` column records whether a POI correlation passed the quality threshold. Failed points are exported as `NaN` for numeric fields and are not interpolated or filled. A frame with no finite strain field is a **normally skipped failed frame**: it contributes no current-frame files, but other valid frames may still be committed if the run has no fatal error. If no analyzed deformation frame has valid strain points, the full-field run fails and is not reported as completed.

If a fatal I/O, solver, or export exception interrupts the run, the staging files already produced by that run are retention-moved to `dic/_failed_runs/<timestamp>/`; they are never left in the `dic/` root as if they were current successful output. The run reports failure rather than committing a partial result. This is distinct from a normally skipped no-finite-strain frame. Old successful outputs remain traceable in `dic/_previous_runs/<timestamp>/`.

Each valid frame also gets `frame_####_parameters.txt`, a human-readable provenance record. It records the fixed `reference_frame_1based` and `reference_filename`, the analyzed `frame_global_1based` and `frame_filename`, `field_roi`, image shape, and effective `subset_size_px`, `step_px`, `strain_window`, `solver`, `zncc_min`, and smoothing settings (plus the sequence fingerprint when available).

The full-field UI exposes a visible optional **Exx overlay** switch. The overlay is written as `frame_NNNN_overlay.png` over the analyzed image and is additional visual QC, not a replacement for the core tables/maps. The 1D export controls do not participate in, and cannot gate, the fixed 2D core output. Preflight requires at least a **3 × 3 POI grid**; a field ROI that is too narrow for three rows or three columns is blocked before processing.

<p align="center">
  <img src="assets/readme/section-02-science.svg" width="100%" alt="02 Scientific contracts: px coordinates, dimensionless strain, and honest NaN.">
</p>

## Virtual-extensometer output

```text
core/      strain_*.txt · optional OPJU · strain plots
qc/        qc_summary.txt
optional/  full CSV, correlation plots, overlays, parameters, publication_figures/
```

Primary 1D TXT:

```text
Frame	EngineeringStrain	TrueStrain
```

```text
engineering strain = (L - L0) / L0
true strain        = ln(L / L0)
PoissonRatio       = - ε_transverse / ε_axial   (engineering)
```

Failed tracking frames stay `NaN`. Poisson uses role-averaged groups; tiny axial magnitude also gives `NaN`.

## Windows quick start

1. Open the [Releases page](https://github.com/D-sudoasd/ezDIC/releases) and download a Windows x64 asset for a version that is currently listed there. This source snapshot does not provide a v0.1.4 ZIP; that ZIP becomes available only after a separate v0.1.4 tag/release is created.
2. Extract the full downloaded folder; the portable package's top-level directory is `ezDIC_Windows_x64`. Keep `_internal/` next to `ezDIC.exe` and retain the license, citation, version, and notice files.
3. Run `ezDIC.exe` on Windows 10/11 x64.

For source use:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe dic_virtual_extensometer_gui_v7_multi_roi_range.py
```

For tests and the release-build toolchain, install the pinned build/test set:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The optional Origin OPJU export additionally requires Windows, OriginPro 2021+, a valid local OriginPro license, and `requirements-origin.txt`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-origin.txt
```

Build a Windows portable package with `powershell -File .\build_release.ps1`. The build script validates release metadata, runs its checks fail-closed, and copies the support files into the package.

## Scientific and implementation limits

Full-field DIC is an in-plane local-subset method using IC-GN / IC-LM with a first-order affine subset warp. It reports a POI grid, not per-pixel values; it is not stereo / 3D DIC, DVC, GPU/MPI, SIFT-guided DIC, or global B-spline FEM. Pixel coordinates and displacements remain in px unless the user supplies an external calibration; strain values are dimensionless. Failed subsets stay `NaN`, and finite output is not by itself experimental validation or uncertainty quantification.

## Cite

```text
Gong, D. (2026). ezDIC (v0.1.4). Zenodo. https://doi.org/10.5281/zenodo.20222465
```

See `CITATION.cff`, `NOTICE_Attribution_and_Usage.txt`, `LICENSE.txt`, and `RELEASE_NOTES_v0.1.4.md` for attribution, redistribution terms, and the release boundary.
