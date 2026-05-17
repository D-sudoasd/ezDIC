import math

import numpy as np
import pandas as pd
import pytest

import dic_virtual_extensometer_gui_v7_multi_roi_range as ezdic


def sample_group_df():
    return pd.DataFrame(
        {
            "frame_global_1based": [1, 2, 3, 4],
            "engineering_strain": [0.0, 0.01, np.nan, -0.005],
            # Deliberately wrong values: export must compute true strain from
            # engineering strain, not trust stale upstream data.
            "true_strain": [99.0, 99.0, 99.0, 99.0],
            "accepted": [True, True, False, True],
            "accept_mode": ["initial", "hard", "rejected", "adaptive"],
            "corr_score_roi1": [1.0, 0.95, 0.2, 0.7],
            "corr_score_roi2": [1.0, 0.93, 0.1, 0.72],
            "group": ["G01", "G01", "G01", "G01"],
            "filename": ["f1.tif", "f2.tif", "f3.tif", "f4.tif"],
            "reason": ["initial frame", "ok", "corr fail", "adaptive ok"],
        }
    )


def sample_poisson_df():
    base = {
        "filename": ["f1.tif", "f2.tif", "f3.tif", "f4.tif"],
        "accept_mode": ["initial", "hard", "hard", "rejected"],
        "corr_score_roi1": [1.0, 0.95, 0.95, 0.2],
        "corr_score_roi2": [1.0, 0.94, 0.94, 0.2],
        "reason": ["initial frame", "ok", "ok", "tracking fail"],
    }
    axial = pd.DataFrame(
        {
            **base,
            "frame_global_1based": [1, 2, 3, 4],
            "engineering_strain": [0.0, 0.02, 1e-7, 0.04],
            "true_strain": [99.0, 99.0, 99.0, 99.0],
            "accepted": [True, True, True, True],
            "group": ["G_axial"] * 4,
        }
    )
    transverse = pd.DataFrame(
        {
            **base,
            "frame_global_1based": [1, 2, 3, 4],
            "engineering_strain": [0.0, -0.006, -0.001, np.nan],
            "true_strain": [99.0, 99.0, 99.0, 99.0],
            "accepted": [True, True, True, False],
            "group": ["G_transverse"] * 4,
        }
    )
    return pd.concat([axial, transverse], ignore_index=True)


def sample_poisson_groups():
    return [
        {"name": "G_axial", "role": "axial", "actual_mode": "y"},
        {"name": "G_transverse", "role": "transverse", "actual_mode": "x"},
    ]


def test_build_core_strain_table_uses_origin_columns_and_recomputes_true_strain():
    table = ezdic.build_core_strain_table(sample_group_df())

    assert list(table.columns) == ["Frame", "EngineeringStrain", "TrueStrain"]
    assert table["Frame"].tolist() == [1, 2, 3, 4]
    assert table.loc[0, "TrueStrain"] == 0.0
    assert math.isclose(table.loc[1, "TrueStrain"], math.log1p(0.01), rel_tol=0, abs_tol=1e-12)
    assert np.isnan(table.loc[2, "EngineeringStrain"])
    assert np.isnan(table.loc[2, "TrueStrain"])


def test_write_origin_txt_is_tab_delimited_with_nan_preserved(tmp_path):
    path = tmp_path / "strain_G01.txt"

    ezdic.write_origin_txt(sample_group_df(), path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Frame\tEngineeringStrain\tTrueStrain"
    assert lines[1] == "1\t0.00000000\t0.00000000"
    assert lines[2] == f"2\t0.01000000\t{math.log1p(0.01):.8f}"
    assert lines[3] == "3\tNaN\tNaN"


def test_build_qc_summary_counts_rejected_adaptive_and_flags_poor_ratio():
    df = pd.concat([sample_group_df()] * 2, ignore_index=True)
    summary = ezdic.build_qc_summary(df)

    g01 = summary["groups"]["G01"]
    assert g01["frames"] == 8
    assert g01["valid_frames"] == 6
    assert g01["rejected_frames"] == 2
    assert g01["adaptive_accepted_frames"] == 2
    assert g01["rejected_frame_list"] == [3, 3]
    assert g01["qc_level"] == "Poor"
    assert summary["overall"]["qc_level"] == "Poor"


def test_plot_engineering_strain_writes_png_with_failure_markers(tmp_path):
    path = tmp_path / "engineering_strain_G01.png"

    ezdic.plot_engineering_strain(sample_group_df(), path, "Engineering strain - G01")

    assert path.exists()
    assert path.stat().st_size > 0


def test_build_poisson_ratio_table_uses_engineering_strain_and_nan_guards():
    table = ezdic.build_poisson_ratio_table(sample_poisson_df(), sample_poisson_groups())

    assert list(table.columns) == [
        "Frame",
        "AxialEngineeringStrain",
        "TransverseEngineeringStrain",
        "PoissonRatio",
    ]
    assert table["Frame"].tolist() == [1, 2, 3, 4]
    assert np.isnan(table.loc[0, "PoissonRatio"])
    assert math.isclose(table.loc[1, "PoissonRatio"], 0.3, rel_tol=0, abs_tol=1e-12)
    assert np.isnan(table.loc[2, "PoissonRatio"])
    assert np.isnan(table.loc[3, "PoissonRatio"])


def test_build_all_groups_strain_table_appends_poisson_columns_when_roles_are_set():
    table = ezdic.build_all_groups_strain_table(sample_poisson_df(), sample_poisson_groups())

    assert "EngineeringStrain_G_axial" in table.columns
    assert "TrueStrain_G_transverse" in table.columns
    assert list(table.columns[-3:]) == [
        "AxialEngineeringStrain",
        "TransverseEngineeringStrain",
        "PoissonRatio",
    ]
    assert math.isclose(table.loc[1, "PoissonRatio"], 0.3, rel_tol=0, abs_tol=1e-12)


def test_build_all_groups_strain_table_keeps_legacy_shape_without_poisson_roles():
    table = ezdic.build_all_groups_strain_table(sample_group_df())

    assert list(table.columns) == ["Frame", "EngineeringStrain_G01", "TrueStrain_G01"]


def test_write_poisson_ratio_txt_is_origin_friendly(tmp_path):
    path = tmp_path / "poisson_ratio.txt"

    ezdic.write_poisson_ratio_txt(sample_poisson_df(), sample_poisson_groups(), path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Frame\tAxialEngineeringStrain\tTransverseEngineeringStrain\tPoissonRatio"
    assert lines[1] == "1\t0.00000000\t0.00000000\tNaN"
    assert lines[2] == "2\t0.02000000\t-0.00600000\t0.30000000"
    assert lines[3] == "3\t0.00000010\t-0.00100000\tNaN"


def test_build_poisson_ratio_table_requires_axial_and_transverse_roles():
    with pytest.raises(RuntimeError, match="拉伸方向 ROI 组"):
        ezdic.build_poisson_ratio_table(sample_poisson_df(), [{"name": "G_axial", "role": "none"}])
