from pathlib import Path
import os
import subprocess
import time

import cv2
import numpy as np
import pytest

import dic_virtual_extensometer_gui_v7_multi_roi_range as ezdic


ROOT = Path(__file__).resolve().parents[1]
DOI = "10.5281/zenodo.20222465"
DOI_URL = f"https://doi.org/{DOI}"


@pytest.fixture(scope="module")
def gui_app():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        app = ezdic.MultiROIGUI(root)
        root.update_idletasks()
        yield root, app
    finally:
        root.destroy()


def write_test_image(path, value=120):
    arr = np.full((100, 140), value, dtype=np.uint8)
    ok, data = cv2.imencode(".png", arr)
    assert ok
    data.tofile(str(path))


def reset_gui_app(app):
    app.image_folder.set("")
    app.output_folder.set("")
    app.search_radius.set(180)
    app.hard_corr.set(0.55)
    app.soft_corr.set(0.35)
    app.strain_mode.set("auto")
    app.sync_strain_mode_display()
    app.roi_role.set("none")
    app.sync_roi_role_display()
    app.tracking_preset.set("标准")
    app.preset_status_var.set("当前追踪模式：标准")
    app.enable_adaptive.set(True)
    app.use_prev_frame_template.set(True)
    app.template_alpha.set(0.70)
    app.max_frame_strain_jump.set("0.01")
    app.enable_fb_check.set(True)
    app.fb_tolerance_px.set(12.0)
    app.overlay_every.set(5)
    app.pixel_size_mm.set("")
    app.auto_align_roi2.set(True)
    app.min_texture_std.set(8.0)
    app.min_texture_contrast.set(25.0)
    app.max_saturated_frac.set(0.20)
    app.export_origin_txt.set(True)
    app.export_engineering_png.set(True)
    app.export_qc_summary.set(True)
    app.export_full_csv.set(False)
    app.export_corr_plot.set(False)
    app.export_overlays.set(False)
    app.export_parameters.set(False)
    if hasattr(app, "export_origin_opju"):
        app.export_origin_opju.set(False)
    app.image_paths = []
    app.loaded_image_folder = None
    app.first_raw = None
    app.first_img8 = None
    app.display_img = None
    app.photo = None
    app.preview_frame_1based.set(1)
    app.start_frame_1based.set(1)
    app.end_frame_1based.set(1)
    app.current_preview_index = 0
    app.roi1 = None
    app.roi2 = None
    app.roi_groups.clear()
    app.next_group_idx = 1
    app.group_name_var.set("")
    app.refresh_group_tree()
    app.canvas.delete("all")


def load_two_frame_sequence(app, folder, output_folder):
    folder.mkdir(parents=True, exist_ok=True)
    write_test_image(folder / "frame_001.png", value=100)
    write_test_image(folder / "frame_002.png", value=130)
    output_folder.mkdir(parents=True, exist_ok=True)
    app.image_folder.set(str(folder))
    app.output_folder.set(str(output_folder))
    app.load_first_image()


def add_basic_roi_group(app):
    app.roi1 = (10, 10, 30, 30)
    app.roi2 = (80, 10, 30, 30)
    app.strain_mode.set("x")
    app.sync_strain_mode_display()
    app.add_current_group()


def test_app_metadata_and_usage_notice_are_explicit():
    assert ezdic.APP_NAME == "ezDIC"
    assert ezdic.APP_VERSION == "0.1.3"
    assert ezdic.APP_DEVELOPER == "Dr. Delun Gong"
    assert ezdic.APP_DOI == DOI
    assert ezdic.APP_DOI_URL == DOI_URL
    assert "developed by Dr. Delun Gong" in ezdic.USAGE_NOTICE
    assert DOI in ezdic.USAGE_NOTICE
    assert "Gong, D. (2026)." in ezdic.CITATION_TEXT
    assert DOI_URL in ezdic.CITATION_TEXT
    assert "claim that they developed this software" in ezdic.USAGE_NOTICE
    assert "redistribute, copy, forward, or share" in ezdic.USAGE_NOTICE


def test_window_title_contains_developer(gui_app):
    root, _app = gui_app
    title = root.title()

    assert title == "ezDIC v0.1.3 - Developed by Dr. Delun Gong - DOI: 10.5281/zenodo.20222465"


def test_gui_initializes_poisson_role_selection(gui_app):
    _root, app = gui_app
    assert app.roi_role.get() == "none"
    assert app.roi_role_display.get() == "普通"


def test_gui_emphasizes_start_analysis_action(gui_app):
    _root, app = gui_app
    assert app.start_button.cget("text") == "开始分析并导出结果"
    assert app.start_button.cget("style") == "Primary.TButton"
    assert "下一步" in app.workflow_hint_var.get()


def test_gui_initial_layout_fits_default_window_height(gui_app):
    root, app = gui_app
    root.update_idletasks()

    assert root.winfo_reqheight() <= 980
    assert int(app.log_text.cget("height")) <= 10


def test_gui_minimum_size_does_not_clip_requested_layout(gui_app):
    root, _app = gui_app
    root.update_idletasks()

    min_w, min_h = root.minsize()
    assert min_w >= root.winfo_reqwidth()
    assert min_h >= root.winfo_reqheight()


def test_gui_layout_fits_research_laptop_viewport(gui_app):
    root, app = gui_app
    root.deiconify()
    root.geometry("1366x768+0+0")
    root.update()
    root.update_idletasks()

    min_w, min_h = root.minsize()
    assert min_w <= 1366
    assert min_h <= 768

    for attr in [
        "project_frame",
        "controls_canvas",
        "controls_panel",
        "image_frame",
        "analysis_frame",
    ]:
        assert getattr(app, attr, None) is not None

    root_w = root.winfo_width()
    root_h = root.winfo_height()
    root_x = root.winfo_rootx()
    root_y = root.winfo_rooty()
    for widget in [app.canvas, app.group_tree, app.start_button, app.progress, app.log_text]:
        assert widget.winfo_width() > 20
        assert widget.winfo_height() > 10
        x0 = widget.winfo_rootx() - root_x
        y0 = widget.winfo_rooty() - root_y
        x1 = x0 + widget.winfo_width()
        y1 = y0 + widget.winfo_height()
        assert 0 <= x0 < root_w
        assert 0 <= y0 < root_h
        assert x1 <= root_w
        assert y1 <= root_h
    root.withdraw()


def test_gui_beginner_workflow_and_key_button_tooltips_are_available(gui_app):
    _root, app = gui_app

    workflow_text = "\n".join(getattr(app, "workflow_step_texts", []))
    assert "图像文件夹" in workflow_text
    assert "ROI" in workflow_text
    assert "开始分析" in workflow_text

    tooltip_targets = [
        ("load_images_button", getattr(app, "load_images_button", None), "加载"),
        ("add_group_button", getattr(app, "add_group_button", None), "ROI"),
        ("start_button", app.start_button, "开始分析"),
    ]
    for name, widget, expected_text in tooltip_targets:
        assert widget is not None, f"{name} should be available for GUI tests"
        assert expected_text in getattr(widget, "_tooltip_text", "")


def test_gui_primary_interactive_controls_have_scientific_tooltips(gui_app):
    _root, app = gui_app

    required_attrs = [
        "image_folder_entry",
        "select_image_button",
        "output_folder_entry",
        "select_output_button",
        "load_images_button",
        "preview_frame_entry",
        "show_preview_button",
        "prev_frame_button",
        "next_frame_button",
        "start_frame_entry",
        "end_frame_entry",
        "set_start_button",
        "set_end_button",
        "strain_mode_box",
        "tracking_preset_box",
        "pixel_size_entry",
        "auto_align_roi2_check",
        "advanced_toggle_btn",
        "search_radius_entry",
        "hard_corr_entry",
        "soft_corr_entry",
        "max_frame_strain_jump_entry",
        "fb_tolerance_entry",
        "template_alpha_entry",
        "min_texture_std_entry",
        "min_texture_contrast_entry",
        "max_saturated_frac_entry",
        "overlay_every_entry",
        "enable_adaptive_check",
        "use_prev_frame_template_check",
        "enable_fb_check_check",
        "roi1_button",
        "roi2_button",
        "align_x_button",
        "align_y_button",
        "group_name_entry",
        "roi_role_box",
        "add_group_button",
        "update_group_button",
        "load_group_button",
        "delete_group_button",
        "clear_rois_button",
        "group_tree",
        "canvas",
        "start_button",
        "usage_notice_button",
    ]

    for attr in required_attrs:
        widget = getattr(app, attr, None)
        assert widget is not None, f"{attr} should be stored for GUI help verification"
        tooltip = getattr(widget, "_tooltip_text", "").strip()
        assert len(tooltip) >= 24, f"{attr} should have a practical tooltip"

    for checkbutton in app.export_checkbuttons:
        tooltip = getattr(checkbutton, "_tooltip_text", "").strip()
        assert len(tooltip) >= 24

    assert "调大" in app.search_radius_entry._tooltip_text
    assert "留空" in app.pixel_size_entry._tooltip_text
    assert "勾选" in app.auto_align_roi2_check._tooltip_text


def test_gui_key_settings_use_light_visual_emphasis(gui_app):
    _root, app = gui_app

    assert app.analysis_range_label.cget("style") == "Key.TLabel"
    assert app.strain_mode_label.cget("style") == "Key.TLabel"
    assert app.export_hint_label.cget("style") == "Warning.TLabel"
    assert app.start_button.cget("style") == "Primary.TButton"


def test_windows_launcher_bat_invokes_source_entry_in_smoke_mode():
    launcher = ROOT / "start_ezDIC.bat"

    assert launcher.exists()
    text = launcher.read_text(encoding="utf-8")
    assert 'pushd "%~dp0"' in text
    assert "dic_virtual_extensometer_gui_v7_multi_roi_range.py" in text
    assert "pause" in text.lower()

    if os.name != "nt":
        pytest.skip("Windows launcher smoke test requires cmd.exe")

    env = os.environ.copy()
    env["EZDIC_LAUNCHER_SMOKE_TEST"] = "1"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(launcher)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "EZDIC launcher smoke test" in output
    assert "dic_virtual_extensometer_gui_v7_multi_roi_range.py" in output


def test_gui_includes_origin_opju_export_option_disabled_by_default(gui_app):
    _root, app = gui_app

    assert app.export_origin_opju.get() is False
    export_texts = [button.cget("text") for button in app.export_checkbuttons]
    assert "Origin OPJU 项目（直接导入 OriginPro）" in export_texts


def test_loading_new_image_folder_clears_previous_roi_state(gui_app, tmp_path, monkeypatch):
    _root, app = gui_app
    reset_gui_app(app)
    monkeypatch.setattr(ezdic.messagebox, "askyesno", lambda *args, **kwargs: True)

    load_two_frame_sequence(app, tmp_path / "images_a", tmp_path / "out_a")
    add_basic_roi_group(app)
    assert len(app.roi_groups) == 1

    load_two_frame_sequence(app, tmp_path / "images_b", tmp_path / "out_b")

    assert app.roi_groups == []
    assert app.roi1 is None
    assert app.roi2 is None
    assert app.next_group_idx == 1


def test_failed_image_load_preserves_previous_valid_sequence(gui_app, tmp_path, monkeypatch):
    _root, app = gui_app
    reset_gui_app(app)
    errors = []
    monkeypatch.setattr(ezdic.messagebox, "showerror", lambda title, message: errors.append((title, message)))

    load_two_frame_sequence(app, tmp_path / "images_good", tmp_path / "out_good")
    old_paths = list(app.image_paths)
    old_preview = app.current_preview_index
    corrupt_dir = tmp_path / "images_bad"
    corrupt_dir.mkdir()
    (corrupt_dir / "bad.png").write_bytes(b"not an image")

    app.image_folder.set(str(corrupt_dir))
    app.load_first_image()

    assert errors
    assert app.image_paths == old_paths
    assert app.current_preview_index == old_preview
    assert app.first_img8 is not None


def test_validate_rejects_output_path_that_is_existing_file(gui_app, tmp_path, monkeypatch):
    _root, app = gui_app
    reset_gui_app(app)
    monkeypatch.setattr(ezdic.messagebox, "askyesno", lambda *args, **kwargs: True)
    load_two_frame_sequence(app, tmp_path / "images", tmp_path / "out")
    add_basic_roi_group(app)
    output_file = tmp_path / "not_a_directory.txt"
    output_file.write_text("occupied", encoding="utf-8")
    app.output_folder.set(str(output_file))

    with pytest.raises(RuntimeError, match="不是文件夹"):
        app.validate_before_processing()


def test_validate_requires_at_least_one_export_option(gui_app, tmp_path, monkeypatch):
    _root, app = gui_app
    reset_gui_app(app)
    monkeypatch.setattr(ezdic.messagebox, "askyesno", lambda *args, **kwargs: True)
    load_two_frame_sequence(app, tmp_path / "images", tmp_path / "out")
    add_basic_roi_group(app)
    app.export_origin_txt.set(False)
    app.export_engineering_png.set(False)
    app.export_qc_summary.set(False)
    app.export_full_csv.set(False)
    app.export_corr_plot.set(False)
    app.export_overlays.set(False)
    app.export_parameters.set(False)
    app.export_origin_opju.set(False)

    with pytest.raises(RuntimeError, match="至少选择一种导出内容"):
        app.validate_before_processing()
    app.export_origin_opju.set(True)
    app.validate_before_processing()


def test_validate_reports_invalid_numeric_inputs_in_chinese(gui_app, tmp_path, monkeypatch):
    _root, app = gui_app
    reset_gui_app(app)
    monkeypatch.setattr(ezdic.messagebox, "askyesno", lambda *args, **kwargs: True)
    load_two_frame_sequence(app, tmp_path / "images", tmp_path / "out")
    add_basic_roi_group(app)

    app.start_frame_1based.set("abc")
    with pytest.raises(RuntimeError, match="起始帧.*整数"):
        app.validate_before_processing()

    app.start_frame_1based.set(1)
    app.search_radius.set("abc")
    with pytest.raises(RuntimeError, match="搜索半径.*整数"):
        app.validate_before_processing()


def test_processing_settings_are_snapshotted_before_worker_thread(gui_app, tmp_path, monkeypatch):
    _root, app = gui_app
    reset_gui_app(app)
    monkeypatch.setattr(ezdic.messagebox, "askyesno", lambda *args, **kwargs: True)
    load_two_frame_sequence(app, tmp_path / "images", tmp_path / "out")
    add_basic_roi_group(app)

    settings = app.build_processing_settings()
    original_output = settings["output_dir"]
    original_paths = list(settings["image_paths"])
    original_groups = list(settings["roi_groups"])
    assert settings["export_origin_opju"] is False

    app.export_origin_opju.set(True)
    assert app.build_processing_settings()["export_origin_opju"] is True

    app.output_folder.set(str(tmp_path / "changed_out"))
    app.image_paths.clear()
    app.roi_groups.clear()

    assert original_output == tmp_path / "out"
    assert settings["output_dir"] == original_output
    assert settings["image_paths"] == original_paths
    assert settings["roi_groups"] == original_groups
    assert settings["roi_groups"] is not app.roi_groups


def test_background_processing_finishes_even_if_ui_queue_is_not_drained(gui_app, tmp_path, monkeypatch):
    _root, app = gui_app
    reset_gui_app(app)
    monkeypatch.setattr(ezdic.messagebox, "showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr(ezdic.messagebox, "showerror", lambda *args, **kwargs: None)
    monkeypatch.setattr(ezdic.messagebox, "askyesno", lambda *args, **kwargs: True)

    image_dir = tmp_path / "images"
    image_dir.mkdir()
    patch = np.arange(900, dtype=np.uint16).reshape(30, 30).astype(np.uint8)
    for idx in range(3):
        arr = np.full((100, 160), 30, dtype=np.uint8)
        arr[30:60, 20 + idx:50 + idx] = patch
        arr[30:60, 90 + idx:120 + idx] = patch
        ok, data = cv2.imencode(".png", arr)
        assert ok
        data.tofile(str(image_dir / f"frame_{idx:03d}.png"))

    app.image_folder.set(str(image_dir))
    app.output_folder.set(str(tmp_path / "out"))
    app.load_first_image()
    app.roi1 = (20, 30, 30, 30)
    app.roi2 = (90, 30, 30, 30)
    app.strain_mode.set("x")
    app.sync_strain_mode_display()
    app.add_current_group()

    app.start_processing()
    deadline = time.time() + 5
    while app.is_processing and time.time() < deadline:
        time.sleep(0.05)

    assert app.is_processing is False
    assert (tmp_path / "out" / "core" / "strain_G01.txt").exists()


def test_origin_opju_failure_does_not_cancel_existing_exports(gui_app, tmp_path, monkeypatch):
    _root, app = gui_app
    reset_gui_app(app)
    monkeypatch.setattr(ezdic.messagebox, "askyesno", lambda *args, **kwargs: True)

    image_dir = tmp_path / "images"
    image_dir.mkdir()
    patch = np.arange(900, dtype=np.uint16).reshape(30, 30).astype(np.uint8)
    for idx in range(3):
        arr = np.full((100, 160), 30, dtype=np.uint8)
        arr[30:60, 20 + idx:50 + idx] = patch
        arr[30:60, 90 + idx:120 + idx] = patch
        ok, data = cv2.imencode(".png", arr)
        assert ok
        data.tofile(str(image_dir / f"frame_{idx:03d}.png"))

    app.image_folder.set(str(image_dir))
    app.output_folder.set(str(tmp_path / "out"))
    app.load_first_image()
    app.roi1 = (20, 30, 30, 30)
    app.roi2 = (90, 30, 30, 30)
    app.strain_mode.set("x")
    app.sync_strain_mode_display()
    app.add_current_group()
    app.export_origin_opju.set(True)

    failures = []

    def fail_origin_export(*args, **kwargs):
        failures.append((args, kwargs))
        raise RuntimeError("OriginPro unavailable")

    monkeypatch.setattr(ezdic, "write_origin_opju_project", fail_origin_export)

    app.process_images(app.build_processing_settings())

    assert failures
    assert (tmp_path / "out" / "core" / "strain_G01.txt").exists()
    assert not (tmp_path / "out" / "core" / "ezDIC_results.opju").exists()


def test_processing_completion_mentions_mean_export_and_opens_output_root(gui_app, tmp_path, monkeypatch):
    _root, app = gui_app
    reset_gui_app(app)
    monkeypatch.setattr(app, "post_to_ui", lambda callback: callback())
    monkeypatch.setattr(ezdic.messagebox, "askyesno", lambda *args, **kwargs: True)

    messages = []
    opened_paths = []
    monkeypatch.setattr(
        ezdic.messagebox,
        "showinfo",
        lambda title, message: messages.append((title, message)),
    )
    monkeypatch.setattr(
        ezdic,
        "open_output_folder",
        lambda path: opened_paths.append(Path(path)),
        raising=False,
    )

    image_dir = tmp_path / "images"
    image_dir.mkdir()
    patch = np.arange(900, dtype=np.uint16).reshape(30, 30).astype(np.uint8)
    for idx in range(3):
        arr = np.full((100, 160), 30, dtype=np.uint8)
        arr[30:60, 20 + idx:50 + idx] = patch
        arr[30:60, 90 + idx:120 + idx] = patch
        ok, data = cv2.imencode(".png", arr)
        assert ok
        data.tofile(str(image_dir / f"frame_{idx:03d}.png"))

    output_dir = tmp_path / "out"
    app.image_folder.set(str(image_dir))
    app.output_folder.set(str(output_dir))
    app.load_first_image()
    for name, y in [("G01", 30), ("G02", 64)]:
        app.group_name_var.set(name)
        app.roi1 = (20, y, 30, 30)
        app.roi2 = (90, y, 30, 30)
        app.strain_mode.set("x")
        app.sync_strain_mode_display()
        app.add_current_group()

    app.process_images(app.build_processing_settings())

    assert (output_dir / "core" / "strain_mean_groups.txt").exists()
    assert messages
    assert messages[-1][0] == "完成"
    assert "平均应变文件: " in messages[-1][1]
    assert "core\\strain_mean_groups.txt" in messages[-1][1]
    assert "strain_all_groups.txt" in messages[-1][1]
    assert opened_paths == [output_dir]


def test_completion_folder_open_failure_is_logged(gui_app, tmp_path, monkeypatch):
    _root, app = gui_app
    reset_gui_app(app)

    messages = []
    log_messages = []
    monkeypatch.setattr(
        ezdic.messagebox,
        "showinfo",
        lambda title, message: messages.append((title, message)),
    )
    monkeypatch.setattr(
        ezdic,
        "open_output_folder",
        lambda path: (_ for _ in ()).throw(RuntimeError("explorer failed")),
        raising=False,
    )
    monkeypatch.setattr(app, "log", lambda message: log_messages.append(message))

    app.show_completion_and_open_output_folder("处理完成。", tmp_path / "out")

    assert messages == [("完成", "处理完成。")]
    assert len(log_messages) == 1
    assert "无法自动打开结果目录" in log_messages[0]
    assert "explorer failed" in log_messages[0]


def test_release_support_files_exist_and_include_usage_limits():
    notice = ROOT / "NOTICE_Attribution_and_Usage.txt"
    readme = ROOT / "README_使用说明.txt"
    github_readme = ROOT / "README.md"
    citation = ROOT / "CITATION.cff"
    version = ROOT / "VERSION.txt"
    zenodo = ROOT / ".zenodo.json"
    release_notes = ROOT / "RELEASE_NOTES_v0.1.3.md"

    assert notice.exists()
    assert readme.exists()
    assert github_readme.exists()
    assert citation.exists()
    assert version.exists()
    assert zenodo.exists()
    assert release_notes.exists()

    notice_text = notice.read_text(encoding="utf-8")
    readme_text = readme.read_text(encoding="utf-8")
    github_readme_text = github_readme.read_text(encoding="utf-8")
    citation_text = citation.read_text(encoding="utf-8")
    version_text = version.read_text(encoding="utf-8")
    zenodo_text = zenodo.read_text(encoding="utf-8")
    release_notes_text = release_notes.read_text(encoding="utf-8")

    assert "Developer:\nDr. Delun Gong" in notice_text
    assert "claim that they developed this software" in notice_text
    assert "redistribute, copy, forward, or share" in notice_text
    assert "Windows 10/11 x64" in readme_text
    assert "Do not copy ezDIC.exe alone" in readme_text
    assert "Dr. Delun Gong" in readme_text
    assert DOI in readme_text
    assert DOI_URL in readme_text
    assert "Virtual extensometer" in github_readme_text
    assert "Origin-compatible TXT" in github_readme_text
    assert "Origin OPJU" in github_readme_text
    assert "OriginPro 2021+" in readme_text
    assert "Digital image correlation" in github_readme_text
    assert "Dr. Delun Gong" in github_readme_text
    assert DOI in github_readme_text
    assert DOI_URL in github_readme_text
    assert f"doi: {DOI}" in citation_text
    assert DOI_URL in citation_text
    assert "ezDIC v0.1.3" in version_text
    assert DOI in version_text
    assert '"upload_type": "software"' in zenodo_text
    assert '"access_right": "restricted"' in zenodo_text
    assert '"title": "ezDIC: Lightweight Virtual Extensometer for Linear Strain Extraction from Image Sequences"' in zenodo_text
    assert "Poisson ratio export and GUI workflow update" in release_notes_text
    assert "How to cite" in release_notes_text
    assert DOI_URL in release_notes_text


def test_pyinstaller_build_files_define_green_folder_release():
    requirements = ROOT / "requirements.txt"
    build_requirements = ROOT / "requirements-build.txt"
    spec = ROOT / "ezDIC.spec"
    build_script = ROOT / "build_release.ps1"

    assert requirements.exists()
    assert build_requirements.exists()
    assert spec.exists()
    assert build_script.exists()

    req_text = requirements.read_text(encoding="utf-8")
    build_req_text = build_requirements.read_text(encoding="utf-8")
    spec_text = spec.read_text(encoding="utf-8")
    script_text = build_script.read_text(encoding="utf-8")

    for package in ["opencv-python", "numpy", "pandas", "matplotlib", "pillow", "originpro"]:
        assert package in req_text

    assert "pyinstaller" in build_req_text.lower()
    assert "name='ezDIC'" in spec_text
    assert "console=False" in spec_text
    assert "release" in script_text
    assert "ezDIC_Windows_x64" in script_text
    assert "Compress-Archive" in script_text
