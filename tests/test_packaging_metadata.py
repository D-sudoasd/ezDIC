from pathlib import Path

import dic_virtual_extensometer_gui_v7_multi_roi_range as ezdic


ROOT = Path(__file__).resolve().parents[1]


def test_app_metadata_and_usage_notice_are_explicit():
    assert ezdic.APP_NAME == "ezDIC"
    assert ezdic.APP_VERSION == "0.1.0"
    assert ezdic.APP_DEVELOPER == "Dr. Delun Gong"
    assert "developed by Dr. Delun Gong" in ezdic.USAGE_NOTICE
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

    assert title == "ezDIC v0.1.0 - Developed by Dr. Delun Gong"


def test_release_support_files_exist_and_include_usage_limits():
    notice = ROOT / "NOTICE_Attribution_and_Usage.txt"
    readme = ROOT / "README_使用说明.txt"
    github_readme = ROOT / "README.md"
    version = ROOT / "VERSION.txt"

    assert notice.exists()
    assert readme.exists()
    assert github_readme.exists()
    assert version.exists()

    notice_text = notice.read_text(encoding="utf-8")
    readme_text = readme.read_text(encoding="utf-8")
    github_readme_text = github_readme.read_text(encoding="utf-8")
    version_text = version.read_text(encoding="utf-8")

    assert "Developer:\nDr. Delun Gong" in notice_text
    assert "claim that they developed this software" in notice_text
    assert "redistribute, copy, forward, or share" in notice_text
    assert "Windows 10/11 x64" in readme_text
    assert "Do not copy ezDIC.exe alone" in readme_text
    assert "Dr. Delun Gong" in readme_text
    assert "Virtual extensometer" in github_readme_text
    assert "Origin-compatible TXT" in github_readme_text
    assert "Digital image correlation" in github_readme_text
    assert "Dr. Delun Gong" in github_readme_text
    assert "ezDIC v0.1.0" in version_text


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
