"""Contract tests for the headless CLI surface (Task 6)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import ezdic_cli


def _config(mode: str, paths: list[str]) -> dict:
    config = {
        "schema_version": 1,
        "analysis_mode": mode,
        "image_paths": paths,
        "start_frame_1based": 1,
        "end_frame_1based": len(paths),
        "reference_frame_1based": 1,
        "output_dir": "out",
    }
    if mode == "extensometer":
        config["roi_groups"] = [
            {
                "name": "g01",
                "roi1": [10, 10, 20, 20],
                "roi2": [50, 10, 20, 20],
                "strain_mode": "auto",
                "role": "axial",
            },
        ]
    else:
        config["field_roi"] = [10, 10, 80, 80]
    return config


def _write_config(tmp_path: Path, config: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_schema_valid_for_both_modes_and_expands_defaults(tmp_path: Path) -> None:
    for mode in ("extensometer", "fullfield"):
        normalized = ezdic_cli.validate_config(_config(mode, ["a.png", "b.png"]))
        assert normalized["schema_version"] == 1
        assert normalized["analysis_mode"] == mode
        assert normalized["reference_frame_1based"] == 1
        if mode == "fullfield":
            assert normalized["quality"]["min_correlation_valid_fraction"] == 0.95
        assert normalized["quality"]["min_strain_valid_fraction"] == 0.80
        assert normalized["quality"]["peak_margin_min"] == 0.02
        assert normalized["quality"]["best_to_second_peak_ratio_min"] == 1.02
        if mode == "fullfield":
            assert normalized["quality"]["max_residual_rms"] is None
        assert normalized["normalization"]["clip"] is True
        assert normalized["export"]["write_manifest"] is True
        assert normalized["transaction"]["enabled"] is True
        if mode == "fullfield":
            assert normalized["solver"]["name"] == "IC-GN"
        assert normalized["normalization"]["policy"] == "reference_percentile"
        assert normalized["transaction"]["enabled"] is True


@pytest.mark.parametrize(
    "mutator,code",
    [
        (lambda c: c.pop("reference_frame_1based"), "CONFIG_SCHEMA_ERROR"),
        (lambda c: c.__setitem__("unexpected", 1), "CONFIG_UNKNOWN_FIELD"),
        (lambda c: c.__setitem__("start_frame_1based", "1"), "CONFIG_TYPE_ERROR"),
        (lambda c: c.__setitem__("end_frame_1based", 3), "CONFIG_INPUT_ERROR"),
        (lambda c: c.setdefault("quality", {}).update({"zncc_min": 2}), "CONFIG_VALUE_ERROR"),
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, mutator, code: str) -> None:
    config = _config("fullfield", ["a.png", "b.png"])
    mutator(config)
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.validate_config(config)
    assert error.value.code == code


def test_nonfinite_and_numeric_string_are_rejected() -> None:
    config = _config("fullfield", ["a.png", "b.png"])
    config["quality"] = {"zncc_min": float("nan")}
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.validate_config(config)
    assert error.value.code == "CONFIG_NONFINITE_NUMBER"

    config = _config("fullfield", ["a.png", "b.png"])
    config["pyramid"] = {"levels": "2"}
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.validate_config(config)
    assert error.value.code == "CONFIG_TYPE_ERROR"

    config = _config("fullfield", ["a.png", "b.png"])
    config["quality"] = {"max_condition_number": 10**1000}
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.validate_config(config)
    assert error.value.code == "CONFIG_NONFINITE_NUMBER"


def test_scientific_units_use_poi_sigma_and_dimensionless_residual() -> None:
    config = _config("fullfield", ["a.png", "b.png"])
    config["solver"] = {"smooth_sigma_poi": 1.25}
    config["quality"] = {"max_residual_rms": 0.15}
    normalized = ezdic_cli.validate_config(config)
    assert normalized["solver"]["smooth_sigma_poi"] == 1.25
    assert normalized["quality"]["max_residual_rms"] == 0.15

    for section, wrong_key in (("solver", "smooth_sigma_px"), ("quality", "max_residual_rms_px")):
        invalid = _config("fullfield", ["a.png", "b.png"])
        invalid[section] = {wrong_key: 1.0}
        with pytest.raises(ezdic_cli.ConfigError) as error:
            ezdic_cli.validate_config(invalid)
        assert error.value.code == "CONFIG_UNKNOWN_FIELD"
        assert wrong_key in error.value.message

    invalid = _config("fullfield", ["a.png", "b.png"])
    invalid["quality"] = {"max_residual_rms": -0.1}
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.validate_config(invalid)
    assert "normalized grayscale residual RMS (dimensionless)" in error.value.message


@pytest.mark.parametrize(
    "section,mutation",
    [
        ("normalization", lambda value: value.update({"policy": "fixed_bounds"})),
        ("normalization", lambda value: value.update({"clip": False})),
        ("transaction", lambda value: value.update({"enabled": False})),
        ("transaction", lambda value: value.update({"archive_previous": False})),
        ("transaction", lambda value: value.update({"retain_failed_staging": False})),
        ("export", lambda value: value.update({"write_manifest": False})),
        ("export", lambda value: value.update({"write_parameters": False})),
        ("quality", lambda value: value.update({"best_to_second_peak_ratio_min": 0.9})),
    ],
)
def test_strict_runtime_safety_contracts_reject_unsafe_settings(section: str, mutation) -> None:
    config = _config("fullfield", ["a.png", "b.png"])
    config[section] = {}
    mutation(config[section])
    with pytest.raises(ezdic_cli.ConfigError):
        ezdic_cli.validate_config(config)


def test_fixed_bounds_requires_finite_ordered_lo_hi() -> None:
    config = _config("fullfield", ["a.png", "b.png"])
    config["normalization"] = {"policy": "fixed_bounds", "bounds": {"lo": 1.0}}
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.validate_config(config)
    assert error.value.code == "CONFIG_SCHEMA_ERROR"

    config["normalization"]["bounds"] = {"lo": 2.0, "hi": 1.0}
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.validate_config(config)
    assert error.value.code == "CONFIG_VALUE_ERROR"


@pytest.mark.parametrize(
    "mode,key",
    [
        ("extensometer", "zncc_min"),
        ("extensometer", "max_condition_number"),
        ("extensometer", "max_residual_rms"),
        ("extensometer", "reject_nonconverged"),
        ("extensometer", "min_correlation_valid_fraction"),
        ("fullfield", "enable_fb_check"),
        ("fullfield", "fb_tolerance_px"),
    ],
)
def test_quality_fields_are_mode_specific(mode: str, key: str) -> None:
    config = _config(mode, ["a.png", "b.png"])
    config["quality"] = {key: False if key == "reject_nonconverged" or key == "enable_fb_check" else 0.1}
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.normalize_config(config)
    assert error.value.code == "CONFIG_UNKNOWN_FIELD"


def test_runtime_code_paths_do_not_change_canonical_config_hash(tmp_path: Path) -> None:
    normalized = ezdic_cli.validate_config(_config("fullfield", ["a.png", "b.png"]))
    with_runtime_binding = dict(normalized)
    with_runtime_binding["_code_paths"] = [str(tmp_path / "ezdic_core.py"), str(tmp_path / "ezdic_cli.py")]
    assert ezdic_cli.config_hash(normalized) == ezdic_cli.config_hash(with_runtime_binding)


def test_fullfield_quality_maps_ratio_min_in_core_direction(tmp_path: Path) -> None:
    image_paths = [tmp_path / "a.png", tmp_path / "b.png"]
    for image_path in image_paths:
        image_path.write_bytes(b"placeholder")
    config = _config("fullfield", [str(path) for path in image_paths])
    config["quality"] = {
        "best_to_second_peak_ratio_min": 1.5,
        "max_residual_rms": None,
    }
    normalized = ezdic_cli.normalize_config(config)

    class StubCore:
        __file__ = __file__

        @staticmethod
        def collect_images(_folder):
            return []

    settings = ezdic_cli.build_core_settings(normalized, StubCore)
    assert settings["peak_ratio_min"] == 1.5
    assert settings["quality"]["max_residual_rms"] == float("inf")


def test_frozen_layout_code_paths_prefer_existing_sources_tree(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "_MEI" / "sources"
    schema_root = source_root / "schemas"
    schema_root.mkdir(parents=True)
    for filename in ("ezdic_core.py", "ezdic_cli.py", "ezdic_benchmark.py"):
        (source_root / filename).write_text("# frozen source\n", encoding="utf-8")
    (schema_root / "run_config_v1.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ezdic_cli.sys, "_MEIPASS", str(tmp_path / "_MEI"), raising=False)
    archive_path = tmp_path / "archive.pyz" / "ezdic_core.py"
    resolved = ezdic_cli._resolve_code_paths(archive_path)
    assert resolved == [
        source_root / "ezdic_core.py",
        source_root / "ezdic_cli.py",
        source_root / "ezdic_benchmark.py",
        schema_root / "run_config_v1.json",
    ]


def test_frozen_layout_code_paths_match_spec_root_schema_and_four_code_files(tmp_path: Path, monkeypatch) -> None:
    bundle_root = tmp_path / "_MEI"
    source_root = bundle_root / "sources"
    (bundle_root / "schemas").mkdir(parents=True)
    source_root.mkdir()
    for filename in ("ezdic_core.py", "ezdic_cli.py", "ezdic_benchmark.py"):
        (source_root / filename).write_text("# frozen source\n", encoding="utf-8")
    (bundle_root / "schemas" / "run_config_v1.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ezdic_cli.sys, "_MEIPASS", str(bundle_root), raising=False)
    resolved = ezdic_cli._resolve_code_paths(bundle_root / "archive.pyz" / "ezdic_core.py")
    assert resolved == [
        source_root / "ezdic_core.py",
        source_root / "ezdic_cli.py",
        source_root / "ezdic_benchmark.py",
        bundle_root / "schemas" / "run_config_v1.json",
    ]


@pytest.mark.parametrize("code", ["LOW_TEXTURE", "SATURATED_TEXTURE", "AMBIGUOUS_TEXTURE"])
def test_texture_rejections_use_scientific_gate_exit_code(code: str) -> None:
    class CoreFailure(RuntimeError):
        pass

    error = CoreFailure(code)
    error.code = code
    assert ezdic_cli._exit_for_core_error(error) == ezdic_cli.EXIT_GATE_ERROR


def test_schema_and_manual_normalizer_agree_on_representative_contracts() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = ezdic_cli.load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    for mode in ("extensometer", "fullfield"):
        config = _config(mode, ["a.png", "b.png"])
        assert not list(validator.iter_errors(config))
        assert ezdic_cli.normalize_config(config)["schema_version"] == 1

    invalid_roi = _config("fullfield", ["a.png", "b.png"])
    invalid_roi["field_roi"] = ["1", 1, 20, 20]
    assert list(validator.iter_errors(invalid_roi))
    with pytest.raises(ezdic_cli.ConfigError):
        ezdic_cli.normalize_config(invalid_roi)

    invalid_transaction = _config("fullfield", ["a.png", "b.png"])
    invalid_transaction["transaction"] = {"archive_previous": False}
    assert list(validator.iter_errors(invalid_transaction))
    with pytest.raises(ezdic_cli.ConfigError):
        ezdic_cli.normalize_config(invalid_transaction)


def test_extensometer_rejects_single_rect_and_requires_roi_pair() -> None:
    config = _config("extensometer", ["a.png", "b.png"])
    config["roi_groups"] = [{"name": "legacy", "rect": [10, 10, 20, 20]}]
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.validate_config(config)
    assert error.value.code == "CONFIG_UNKNOWN_FIELD"

    config["roi_groups"] = [{"name": "incomplete", "roi1": [10, 10, 20, 20]}]
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.validate_config(config)
    assert error.value.code == "CONFIG_SCHEMA_ERROR"

    config["roi_groups"] = [
        {
            "name": "g01",
            "roi1": [10, 10, 20, 20],
            "roi2": [50, 10, 20, 20],
            "strain_mode": "bad",
        }
    ]
    with pytest.raises(ezdic_cli.ConfigError) as error:
        ezdic_cli.validate_config(config)
    assert error.value.code == "CONFIG_VALUE_ERROR"


def test_cli_validate_prints_canonical_config_and_help_is_headless(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _config("fullfield", ["a.png", "b.png"]))
    result = subprocess.run(
        [sys.executable, "-m", "ezdic_cli", "validate-config", "--config", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["output_dir"] == str((tmp_path / "out").resolve())
    assert output["field_roi_reference_frame_1based"] == 1

    help_result = subprocess.run(
        [sys.executable, "-m", "ezdic_cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0
    assert "validate-config" in help_result.stdout
    assert "tkinter" not in help_result.stdout


def test_cli_invalid_json_has_stable_error_and_exit_code_2(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "ezdic_cli", "validate-config", "--config", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == ezdic_cli.EXIT_CONFIG_ERROR
    error = json.loads(result.stderr)
    assert error["error_code"] == "CONFIG_JSON_ERROR"
    assert error["exit_code"] == 2


@pytest.mark.parametrize("command", ["run", "verify-manifest"])
def test_run_and_verify_commands_use_their_stable_error_codes(command: str) -> None:
    args = [sys.executable, "-m", "ezdic_cli", command]
    if command == "run":
        args += ["--config", "missing.json"]
    elif command == "verify-manifest":
        args += ["--manifest", "missing.json"]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    expected_exit = ezdic_cli.EXIT_CONFIG_ERROR if command == "run" else ezdic_cli.EXIT_GATE_ERROR
    assert result.returncode == expected_exit
    error = json.loads(result.stderr)
    assert error["exit_code"] == expected_exit


def test_benchmark_without_output_is_structured_config_error() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ezdic_cli", "benchmark"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == ezdic_cli.EXIT_CONFIG_ERROR
    error = json.loads(result.stderr)
    assert error["error_code"] == "BENCHMARK_OUTPUT_REQUIRED"
