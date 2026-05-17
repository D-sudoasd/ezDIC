from pathlib import Path

import dic_virtual_extensometer_gui_v7_multi_roi_range as ezdic


ROOT = Path(__file__).resolve().parents[1]
DOI = "10.5281/zenodo.20222465"
DOI_URL = f"https://doi.org/{DOI}"


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


def test_window_title_contains_developer():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        ezdic.MultiROIGUI(root)
        title = root.title()
    finally:
        root.destroy()

    assert title == "ezDIC v0.1.3 - Developed by Dr. Delun Gong - DOI: 10.5281/zenodo.20222465"


def test_gui_initializes_poisson_role_selection():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        app = ezdic.MultiROIGUI(root)
        assert app.roi_role.get() == "none"
        assert app.roi_role_display.get() == "普通"
    finally:
        root.destroy()


def test_gui_emphasizes_start_analysis_action():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        app = ezdic.MultiROIGUI(root)
        assert app.start_button.cget("text") == "开始分析并导出结果"
        assert app.start_button.cget("style") == "Primary.TButton"
        assert "下一步" in app.workflow_hint_var.get()
    finally:
        root.destroy()


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

    for package in ["opencv-python", "numpy", "pandas", "matplotlib", "pillow"]:
        assert package in req_text

    assert "pyinstaller" in build_req_text.lower()
    assert "name='ezDIC'" in spec_text
    assert "console=False" in spec_text
    assert "release" in script_text
    assert "ezDIC_Windows_x64" in script_text
    assert "Compress-Archive" in script_text
