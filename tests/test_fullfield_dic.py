"""Gating tests for shipped 2D DIC (IC-GN / IC-LM) against known warps."""
import math

import numpy as np
import pytest

import dic_virtual_extensometer_gui_v7_multi_roi_range as ezdic


def _speckle_pair_translation(tx, ty, *, seed=3, size=128):
    reference = ezdic.generate_synthetic_speckle(size, size, seed=seed)
    deformed = ezdic.warp_image_translation(reference, tx, ty)
    roi = (18, 18, size - 36, size - 36)
    return reference, deformed, roi


def _speckle_pair_stretch(lambda_x, lambda_y=1.0, *, seed=3, size=128):
    reference = ezdic.generate_synthetic_speckle(size, size, seed=seed)
    F = np.array([[lambda_x, 0.0], [0.0, lambda_y]], dtype=float)
    deformed = ezdic.warp_image_deformation_gradient(reference, F)
    roi = (20, 20, size - 40, size - 40)
    return reference, deformed, roi, F


@pytest.mark.parametrize("solver", [ezdic.DIC_SOLVER_ICGN, ezdic.DIC_SOLVER_ICLM])
def test_ic_solvers_recover_known_subpixel_translation(solver):
    tx, ty = 1.37, -0.62
    reference, deformed, roi = _speckle_pair_translation(tx, ty)
    field = ezdic.run_2d_dic(
        reference,
        deformed,
        roi,
        subset_size=21,
        step=10,
        solver=solver,
        search_radius=8,
        zncc_min=0.75,
        strain_window=5,
        smooth_sigma=0.0,
    )

    assert field["solver"] == solver
    assert field["u"] is not ezdic.run_2d_dic  # shipped entry, not a mock
    valid = np.asarray(field["valid"], dtype=bool)
    assert int(valid.sum()) >= 20
    mean_u = float(np.nanmean(field["u"]))
    mean_v = float(np.nanmean(field["v"]))
    assert mean_u == pytest.approx(tx, abs=0.05)
    assert mean_v == pytest.approx(ty, abs=0.05)
    assert float(np.nanmean(field["zncc"])) > 0.95


@pytest.mark.parametrize("solver", [ezdic.DIC_SOLVER_ICGN, ezdic.DIC_SOLVER_ICLM])
def test_green_lagrange_matches_applied_stretch(solver):
    lambda_x = 1.02
    reference, deformed, roi, F = _speckle_pair_stretch(lambda_x)
    oracle = ezdic.green_lagrange_from_F(F)
    field = ezdic.run_2d_dic(
        reference,
        deformed,
        roi,
        subset_size=21,
        step=8,
        solver=solver,
        search_radius=6,
        zncc_min=0.75,
        strain_window=5,
        smooth_sigma=0.0,
    )

    mean_exx = float(np.nanmean(np.asarray(field["Exx"], dtype=float)))
    mean_eyy = float(np.nanmean(np.asarray(field["Eyy"], dtype=float)))
    mean_exy = float(np.nanmean(np.asarray(field["Exy"], dtype=float)))
    assert mean_exx == pytest.approx(oracle["Exx"], abs=0.003)
    assert mean_eyy == pytest.approx(oracle["Eyy"], abs=0.003)
    assert mean_exy == pytest.approx(oracle["Exy"], abs=0.003)
    inf_exx = float(np.nanmean(np.asarray(field["exx"], dtype=float)))
    assert inf_exx == pytest.approx(lambda_x - 1.0, abs=0.004)


def test_failed_and_out_of_roi_points_stay_nonfinite():
    tx, ty = 0.55, 0.40
    reference, deformed, roi = _speckle_pair_translation(tx, ty, seed=11, size=128)
    wrecked = deformed.copy()
    wrecked[48:80, 48:80] = 28.0
    field = ezdic.run_2d_dic(
        reference,
        wrecked,
        roi,
        subset_size=21,
        step=10,
        solver=ezdic.DIC_SOLVER_ICGN,
        zncc_min=0.8,
        strain_window=5,
        smooth_sigma=1.5,
    )
    valid = np.asarray(field["valid"], dtype=bool)
    u = np.asarray(field["u"], dtype=float)
    v = np.asarray(field["v"], dtype=float)
    exx = np.asarray(field["Exx"], dtype=float).ravel()
    xs = np.asarray(field["x"], dtype=float)
    ys = np.asarray(field["y"], dtype=float)

    assert int(valid.sum()) >= 8
    assert int((~valid).sum()) >= 1
    assert not np.isfinite(u[~valid]).any()
    assert not np.isfinite(v[~valid]).any()
    assert not np.isfinite(exx[~valid]).any()
    assert np.isfinite(u[valid]).all()
    # POIs whose subset sits inside the destroyed patch must fail.
    half = 10
    in_wreck = (xs - half >= 48) & (xs + half <= 80) & (ys - half >= 48) & (ys + half <= 80)
    if in_wreck.any():
        assert not valid[in_wreck].any()

    # Points are only generated inside the ROI; a tiny ROI cannot host a subset.
    X, Y = ezdic.build_poi_grid((0, 0, 8, 8), subset_size=21, step=5, image_shape=reference.shape)
    assert X.size == 0
    assert Y.size == 0

    flat = np.full_like(reference, 40.0)
    all_fail = ezdic.run_2d_dic(flat, wrecked, roi, subset_size=21, step=12, zncc_min=0.8)
    assert not np.asarray(all_fail["valid"]).any()
    assert not np.isfinite(all_fail["u"]).any()


def test_dic_table_and_colormap_use_plot_presets(tmp_path):
    tx, ty = 0.80, -0.35
    reference, deformed, roi = _speckle_pair_translation(tx, ty, seed=5)
    field = ezdic.run_2d_dic(
        reference, deformed, roi, subset_size=21, step=12, solver=ezdic.DIC_SOLVER_ICGN
    )
    table = ezdic.dic_field_to_dataframe(field)
    assert list(table.columns) == [
        "x",
        "y",
        "u",
        "v",
        "zncc",
        "valid",
        "Exx",
        "Eyy",
        "Exy",
        "exx",
        "eyy",
        "exy",
    ]
    txt_path = tmp_path / "field.txt"
    ezdic.write_dic_field_txt(field, txt_path)
    text = txt_path.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("x\ty\tu\tv")
    plot_path = tmp_path / "Exx.png"
    ezdic.plot_dic_field_map(field, plot_path, component="Exx", preset_name="publication")
    assert plot_path.exists()
    assert plot_path.stat().st_size > 0

    fig, ax, _preset = ezdic.create_plot_figure("publication")
    mesh = ezdic.render_dic_field_on_axes(ax, field, "u")
    cbar = ezdic.add_dic_colorbar(fig, ax, mesh, "u (px)", preset_name="publication")
    assert cbar is not None
    ezdic.plt.close(fig)


def test_run_2d_dic_sequence_matches_single_frame():
    reference, deformed, roi = _speckle_pair_translation(1.1, -0.4, seed=8)
    single = ezdic.run_2d_dic(reference, deformed, roi, subset_size=21, step=12)
    batch = ezdic.run_2d_dic_sequence(reference, [deformed], roi, subset_size=21, step=12)
    assert len(batch) == 1
    assert float(np.nanmean(batch[0]["u"])) == pytest.approx(float(np.nanmean(single["u"])), abs=1e-9)


def test_ic_refinement_beats_integer_guess_on_shipped_icgn():
    tx, ty = 1.37, -0.62
    reference, deformed, roi = _speckle_pair_translation(tx, ty, seed=3)
    x = y = 64.0
    u0, v0, cc = ezdic.integer_cc_guess(reference, deformed, x, y, 21, search_radius=8)
    assert cc > 0.5
    refined = ezdic.refine_subset_icgn(
        reference, deformed, x, y, 21, p0=[u0, 0.0, 0.0, v0, 0.0, 0.0]
    )
    assert refined is not None
    assert refined["zncc"] > 0.98
    assert abs(refined["u"] - tx) < 0.05
    assert abs(refined["v"] - ty) < 0.05
    assert abs(refined["u"] - tx) <= abs(u0 - tx) + 1e-9
    lm = ezdic.refine_subset_iclm(
        reference, deformed, x, y, 21, p0=[u0, 0.0, 0.0, v0, 0.0, 0.0]
    )
    assert lm is not None
    assert abs(lm["u"] - tx) < 0.05
    assert abs(lm["v"] - ty) < 0.05


def test_green_lagrange_oracle_matches_analytic_stretch():
    F = np.array([[1.02, 0.0], [0.0, 1.0]])
    gl = ezdic.green_lagrange_from_F(F)
    expected = 0.5 * (1.02 ** 2 - 1.0)
    assert math.isclose(gl["Exx"], expected, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(gl["Eyy"], 0.0, abs_tol=1e-12)
    assert math.isclose(gl["Exy"], 0.0, abs_tol=1e-12)
