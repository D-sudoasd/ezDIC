import math
import builtins

import numpy as np
import pandas as pd
import pytest
from PIL import Image

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


def sample_mean_df():
    base = {
        "frame_global_1based": [1, 2, 3],
        "filename": ["f1.tif", "f2.tif", "f3.tif"],
        "accept_mode": ["initial", "hard", "hard"],
        "corr_score_roi1": [1.0, 0.95, 0.95],
        "corr_score_roi2": [1.0, 0.94, 0.94],
        "reason": ["initial frame", "ok", "ok"],
    }
    gx1 = pd.DataFrame(
        {
            **base,
            "engineering_strain": [0.0, 0.01, 0.02],
            "true_strain": [99.0, 99.0, 99.0],
            "accepted": [True, True, True],
            "group": ["G_x1"] * 3,
        }
    )
    gx2 = pd.DataFrame(
        {
            **base,
            "engineering_strain": [0.0, 0.03, 0.04],
            "true_strain": [99.0, 99.0, 99.0],
            "accepted": [True, True, False],
            "group": ["G_x2"] * 3,
        }
    )
    gy1 = pd.DataFrame(
        {
            **base,
            "engineering_strain": [0.0, -0.02, -0.03],
            "true_strain": [99.0, 99.0, 99.0],
            "accepted": [True, True, True],
            "group": ["G_y1"] * 3,
        }
    )
    return pd.concat([gx1, gx2, gy1], ignore_index=True)


def sample_mean_groups():
    return [
        {"name": "G_x1", "role": "none", "actual_mode": "x"},
        {"name": "G_x2", "role": "none", "actual_mode": "x"},
        {"name": "G_y1", "role": "none", "actual_mode": "y"},
    ]


def sample_multi_poisson_df():
    base = {
        "frame_global_1based": [1, 2, 3],
        "filename": ["f1.tif", "f2.tif", "f3.tif"],
        "accept_mode": ["initial", "hard", "hard"],
        "corr_score_roi1": [1.0, 0.95, 0.95],
        "corr_score_roi2": [1.0, 0.94, 0.94],
        "reason": ["initial frame", "ok", "ok"],
    }
    rows = []
    for name, strains, accepted in [
        ("A1", [0.0, 0.02, 0.04], [True, True, True]),
        ("A2", [0.0, 0.04, 0.08], [True, True, True]),
        ("T1", [0.0, -0.006, -0.012], [True, True, True]),
        ("T2", [0.0, -0.012, -0.024], [True, True, False]),
    ]:
        rows.append(
            pd.DataFrame(
                {
                    **base,
                    "engineering_strain": strains,
                    "true_strain": [99.0, 99.0, 99.0],
                    "accepted": accepted,
                    "group": [name] * 3,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def sample_multi_poisson_groups():
    return [
        {"name": "A1", "role": "axial", "actual_mode": "y"},
        {"name": "A2", "role": "axial", "actual_mode": "y"},
        {"name": "T1", "role": "transverse", "actual_mode": "x"},
        {"name": "T2", "role": "transverse", "actual_mode": "x"},
    ]


class FakeOriginWorksheet:
    def __init__(self, name):
        self.name = name
        self.dataframes = []

    def from_df(self, df):
        self.dataframes.append(df.copy())


class FakeOriginModule:
    def __init__(self, save_result=True, new_error=None):
        self.save_result = save_result
        self.new_error = new_error
        self.new_calls = []
        self.new_sheet_calls = []
        self.saved_paths = []
        self.worksheets = []

    def new(self, asksave=False):
        self.new_calls.append(asksave)
        if self.new_error is not None:
            raise self.new_error

    def new_sheet(self, type_="w", lname="", template="", hidden=False):
        self.new_sheet_calls.append(
            {"type": type_, "lname": lname, "template": template, "hidden": hidden}
        )
        worksheet = FakeOriginWorksheet(lname)
        self.worksheets.append(worksheet)
        return worksheet

    def save(self, path=""):
        self.saved_paths.append(path)
        return self.save_result


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


def test_publication_plot_presets_and_vector_export_are_available(tmp_path):
    preset = ezdic.PLOT_EXPORT_PRESETS["publication"]
    assert preset["dpi"] >= 600
    assert "pdf" in ezdic.PLOT_EXPORT_FORMATS
    assert "svg" in ezdic.PLOT_EXPORT_FORMATS
    assert "eps" in ezdic.PLOT_EXPORT_FORMATS
    assert "tiff" in ezdic.PLOT_EXPORT_FORMATS

    path = tmp_path / "engineering_strain_G01.svg"
    ezdic.plot_engineering_strain(sample_group_df(), path, "Engineering strain - G01", preset_name="single_column")

    text = path.read_text(encoding="utf-8")
    assert "<svg" in text
    assert "Engineering strain" in text

    eps_path = tmp_path / "engineering_strain_G01.eps"
    ezdic.plot_engineering_strain(sample_group_df(), eps_path, "Engineering strain - G01", preset_name="single_column")
    assert eps_path.exists()
    assert eps_path.stat().st_size > 0


def test_plot_presets_include_colorbar_style_controls():
    required_keys = {
        "colorbar_label_size",
        "colorbar_tick_size",
        "colorbar_fraction",
        "colorbar_pad",
    }

    for name, preset in ezdic.PLOT_EXPORT_PRESETS.items():
        missing = required_keys - set(preset)
        assert not missing, f"{name} missing colorbar preset keys: {sorted(missing)}"


def test_publication_bitmap_exports_keep_submission_dpi_metadata(tmp_path):
    for suffix in [".png", ".tiff"]:
        path = tmp_path / f"engineering_strain_G01{suffix}"

        ezdic.plot_engineering_strain(sample_group_df(), path, "Engineering strain - G01", preset_name="publication")

        with Image.open(path) as image:
            dpi = image.info.get("dpi") or image.info.get("resolution")
        assert dpi is not None
        assert dpi[0] >= 590
        assert dpi[1] >= 590


def test_save_plot_figure_uses_tight_bbox_with_small_padding(monkeypatch, tmp_path):
    fig, _ax, _preset = ezdic.create_plot_figure("publication")
    captured = {}

    def fake_savefig(path, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(fig, "savefig", fake_savefig)

    ezdic.save_plot_figure(fig, tmp_path / "figure.png", preset_name="publication")

    assert captured["dpi"] == ezdic.PLOT_EXPORT_PRESETS["publication"]["dpi"]
    assert captured["bbox_inches"] == "tight"
    assert captured["facecolor"] == "white"
    assert 0 < captured["pad_inches"] <= 0.08


def test_build_mean_strain_table_groups_by_role_and_mode_and_counts_valid_groups():
    table = ezdic.build_mean_strain_table(sample_mean_df(), sample_mean_groups())

    assert list(table.columns) == [
        "Frame",
        "MeanEngineeringStrain_none_x",
        "MeanTrueStrain_none_x",
        "StdEngineeringStrain_none_x",
        "SemEngineeringStrain_none_x",
        "ValidGroupCount_none_x",
        "MeanEngineeringStrain_none_y",
        "MeanTrueStrain_none_y",
        "StdEngineeringStrain_none_y",
        "SemEngineeringStrain_none_y",
        "ValidGroupCount_none_y",
    ]
    assert table["Frame"].tolist() == [1, 2, 3]
    assert math.isclose(table.loc[1, "MeanEngineeringStrain_none_x"], 0.02, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(table.loc[1, "MeanTrueStrain_none_x"], math.log1p(0.02), rel_tol=0, abs_tol=1e-12)
    assert math.isclose(
        table.loc[1, "StdEngineeringStrain_none_x"],
        math.sqrt(0.0002),
        rel_tol=0,
        abs_tol=1e-12,
    )
    assert math.isclose(table.loc[1, "SemEngineeringStrain_none_x"], 0.01, rel_tol=0, abs_tol=1e-12)
    assert table.loc[1, "ValidGroupCount_none_x"] == 2
    assert math.isclose(table.loc[2, "MeanEngineeringStrain_none_x"], 0.02, rel_tol=0, abs_tol=1e-12)
    assert np.isnan(table.loc[2, "StdEngineeringStrain_none_x"])
    assert np.isnan(table.loc[2, "SemEngineeringStrain_none_x"])
    assert table.loc[2, "ValidGroupCount_none_x"] == 1
    assert math.isclose(table.loc[1, "MeanEngineeringStrain_none_y"], -0.02, rel_tol=0, abs_tol=1e-12)


def test_build_all_groups_strain_table_appends_mean_columns_when_groups_are_provided():
    table = ezdic.build_all_groups_strain_table(sample_mean_df(), sample_mean_groups())

    assert "EngineeringStrain_G_x1" in table.columns
    assert "EngineeringStrain_G_x2" in table.columns
    assert "MeanEngineeringStrain_none_x" in table.columns
    assert "ValidGroupCount_none_y" in table.columns
    assert math.isclose(table.loc[1, "MeanEngineeringStrain_none_x"], 0.02, rel_tol=0, abs_tol=1e-12)


def test_write_mean_groups_origin_txt_is_origin_friendly(tmp_path):
    path = tmp_path / "strain_mean_groups.txt"

    ezdic.write_mean_groups_origin_txt(sample_mean_df(), sample_mean_groups(), path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("Frame\tMeanEngineeringStrain_none_x\tMeanTrueStrain_none_x")
    assert lines[2].startswith(f"2\t0.02000000\t{math.log1p(0.02):.8f}\t")


def test_plot_all_groups_engineering_strain_writes_png_with_mean_curves(tmp_path):
    path = tmp_path / "engineering_strain_all_groups.png"

    ezdic.plot_all_groups_engineering_strain(sample_mean_df(), sample_mean_groups(), path)

    assert path.exists()
    assert path.stat().st_size > 0


def test_build_origin_project_tables_includes_all_core_tables_and_columns():
    tables = ezdic.build_origin_project_tables(sample_multi_poisson_df(), sample_multi_poisson_groups())
    table_map = dict(tables)

    assert list(table_map) == [
        "strain_A1",
        "strain_A2",
        "strain_T1",
        "strain_T2",
        "strain_all_groups",
        "strain_mean_groups",
        "poisson_ratio",
    ]
    assert list(table_map["strain_A1"].columns) == ["Frame", "EngineeringStrain", "TrueStrain"]
    assert "MeanEngineeringStrain_axial_y" in table_map["strain_all_groups"].columns
    assert "MeanEngineeringStrain_transverse_x" in table_map["strain_mean_groups"].columns
    assert list(table_map["poisson_ratio"].columns) == [
        "Frame",
        "AxialEngineeringStrain",
        "TransverseEngineeringStrain",
        "PoissonRatio",
    ]


def test_write_origin_opju_project_uses_originpro_api_and_saves_project(tmp_path):
    fake_origin = FakeOriginModule()
    path = tmp_path / "core" / "ezDIC_results.opju"

    result = ezdic.write_origin_opju_project(
        sample_multi_poisson_df(),
        sample_multi_poisson_groups(),
        path,
        origin_module=fake_origin,
    )

    assert result == path
    assert fake_origin.new_calls == [True]
    assert fake_origin.saved_paths == [str(path)]
    assert [call["lname"] for call in fake_origin.new_sheet_calls] == [
        "strain_A1",
        "strain_A2",
        "strain_T1",
        "strain_T2",
        "strain_all_groups",
        "strain_mean_groups",
        "poisson_ratio",
    ]
    assert fake_origin.worksheets[0].dataframes[0]["Frame"].tolist() == [1, 2, 3]
    assert path.parent.exists()


def test_write_origin_opju_project_reports_missing_originpro(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "originpro":
            raise ImportError("No module named originpro")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="originpro"):
        ezdic.write_origin_opju_project(sample_group_df(), [{"name": "G01"}], tmp_path / "out.opju")


def test_write_origin_opju_project_raises_when_origin_save_fails(tmp_path):
    fake_origin = FakeOriginModule(save_result=False)

    with pytest.raises(RuntimeError, match="保存 Origin OPJU 项目失败"):
        ezdic.write_origin_opju_project(
            sample_group_df(),
            [{"name": "G01", "role": "none", "actual_mode": "x"}],
            tmp_path / "out.opju",
            origin_module=fake_origin,
        )


def test_write_origin_opju_project_wraps_origin_com_errors(tmp_path):
    fake_origin = FakeOriginModule(new_error=RuntimeError("COM startup failed"))

    with pytest.raises(RuntimeError, match="生成 Origin OPJU 项目失败"):
        ezdic.write_origin_opju_project(
            sample_group_df(),
            [{"name": "G01", "role": "none", "actual_mode": "x"}],
            tmp_path / "out.opju",
            origin_module=fake_origin,
        )


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


def test_build_poisson_ratio_table_uses_mean_strains_for_multiple_role_groups():
    table = ezdic.build_poisson_ratio_table(sample_multi_poisson_df(), sample_multi_poisson_groups())

    assert list(table.columns) == [
        "Frame",
        "AxialEngineeringStrain",
        "TransverseEngineeringStrain",
        "PoissonRatio",
    ]
    assert np.isnan(table.loc[0, "PoissonRatio"])
    assert math.isclose(table.loc[1, "AxialEngineeringStrain"], 0.03, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(table.loc[1, "TransverseEngineeringStrain"], -0.009, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(table.loc[1, "PoissonRatio"], 0.3, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(table.loc[2, "AxialEngineeringStrain"], 0.06, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(table.loc[2, "TransverseEngineeringStrain"], -0.012, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(table.loc[2, "PoissonRatio"], 0.2, rel_tol=0, abs_tol=1e-12)


def test_build_poisson_ratio_table_rejects_mixed_modes_within_role():
    groups = sample_multi_poisson_groups()
    groups[1] = {"name": "A2", "role": "axial", "actual_mode": "x"}

    with pytest.raises(RuntimeError, match="actual_mode"):
        ezdic.build_poisson_ratio_table(sample_multi_poisson_df(), groups)


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
