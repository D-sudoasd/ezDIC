"""Regression tests for the GUI-independent input/provenance boundary."""

import os

import numpy as np
import pytest

import ezdic_core as core
import dic_virtual_extensometer_gui_v7_multi_roi_range as gui


def test_nonfinite_array_and_decoded_image_fail_closed(monkeypatch, tmp_path):
    bad = np.ones((8, 8), dtype=np.float32)
    bad[2, 3] = np.nan
    with pytest.raises(core.CoreError) as array_exc:
        core.normalize_to_uint8(bad)
    assert array_exc.value.code == "NONFINITE_IMAGE"
    assert array_exc.value.details["count"] == 1

    image_path = tmp_path / "nan.tiff"
    image_path.write_bytes(b"not a real image")
    monkeypatch.setattr(core.cv2, "imdecode", lambda *_args, **_kwargs: bad)
    with pytest.raises(core.CoreError) as read_exc:
        core.read_gray_image(image_path)
    assert read_exc.value.code == "NONFINITE_IMAGE"
    assert read_exc.value.details["path"] == str(image_path)
    assert read_exc.value.details["count"] == 1


def test_reference_normalization_reuses_one_policy_and_records_metadata():
    reference = np.arange(100, dtype=np.float32).reshape(10, 10)
    frame = np.full_like(reference, 200.0)
    policy = core.compute_reference_normalization(reference)
    reference8, reference_meta = core.normalize_with_bounds(
        reference, policy, return_metadata=True
    )
    frame8, frame_meta = core.normalize_with_bounds(
        frame, policy, return_metadata=True
    )

    assert reference8.dtype == np.uint8
    assert frame8.dtype == np.uint8
    assert reference_meta["bounds"] == frame_meta["bounds"] == policy["reference_bounds"]
    assert reference_meta["input_dtype"] == frame_meta["input_dtype"] == "float32"
    assert reference_meta["shape"] == frame_meta["shape"] == [10, 10]
    assert frame_meta["clip_fraction_high"] == pytest.approx(1.0)

    sequence = core.normalize_sequence_frames(reference, [frame, reference])
    assert sequence["metadata"]["bounds"] == policy["reference_bounds"]
    assert all(
        item["bounds"] == policy["reference_bounds"]
        for item in sequence["metadata"]["frames"]
    )


def test_ordered_input_identity_detects_byte_change_with_restored_mtime(tmp_path):
    path = tmp_path / "frame_001.bin"
    path.write_bytes(b"0123456789")
    before = core.ordered_input_manifest([path])
    original_mtime = before[0]["mtime_ns"]
    path.write_bytes(b"012345678X")
    os.utime(path, ns=(original_mtime, original_mtime))
    after = core.ordered_input_manifest([path])

    assert before[0]["path"] == after[0]["path"]
    assert before[0]["size"] == after[0]["size"]
    assert before[0]["mtime_ns"] == after[0]["mtime_ns"]
    assert before[0]["sha256"] != after[0]["sha256"]

    config = {"z": 0, "a": [1, 2]}
    assert core.canonical_json_hash(config) == core.canonical_json_hash(
        {"a": [1, 2], "z": 0}
    )


def test_structure_tensor_rejects_one_direction_stripe_and_accepts_speckle():
    x = np.linspace(0, 16 * np.pi, 128, dtype=np.float32)
    stripe = (128.0 + 100.0 * np.sin(x)[None, :]).repeat(128, axis=0)
    speckle = core.generate_synthetic_speckle(128, 128, seed=17)
    roi = (10, 10, 100, 100)

    stripe_metrics = core.roi_texture_metrics(stripe, roi)
    speckle_metrics = core.roi_texture_metrics(speckle, roi)
    assert stripe_metrics["structure_tensor_ratio"] < 0.01
    assert speckle_metrics["structure_tensor_ratio"] > core.DEFAULT_TEXTURE_MIN_STRUCTURE_RATIO
    assert core.texture_failure_code(stripe_metrics, 8, 25, 0.2) == "AMBIGUOUS_TEXTURE"
    assert core.texture_failure_code(speckle_metrics, 8, 25, 0.2) is None
    with pytest.raises(core.CoreError) as exc_info:
        core.require_texture(stripe, roi)
    assert exc_info.value.code == "AMBIGUOUS_TEXTURE"


@pytest.mark.parametrize("period, phase", [(12, 0.0), (17, 0.37), (100, 1.2)])
def test_rank_one_periodic_discriminator_rejects_multiple_periods_and_phases(period, phase):
    yy, xx = np.indices((128, 128), dtype=np.float64)
    stripe = (128.0 + 100.0 * np.sin(2.0 * np.pi * xx / period + phase)).astype(np.float32)
    metrics = core.roi_texture_metrics(stripe, (20, 20, 40, 40))

    assert metrics["metrics_version"] == core.TEXTURE_METRICS_VERSION
    assert metrics["discriminator_version"] == core.TEXTURE_DISCRIMINATOR_VERSION
    assert metrics["structure_tensor_ratio"] < core.DEFAULT_TEXTURE_MIN_STRUCTURE_RATIO
    assert core.texture_failure_code(metrics, 8.0, 25.0, 0.20) == "AMBIGUOUS_TEXTURE"


def test_corrupt_existing_image_is_structured_input_file_error(tmp_path):
    path = tmp_path / "corrupt.png"
    path.write_bytes(b"not-an-image")
    with pytest.raises(core.CoreError) as error:
        core.read_gray_image(path)
    assert error.value.code == "INPUT_FILE_ERROR"
    assert error.value.details["path"] == str(path)
    assert error.value.details["stage"] == "decode"


def test_gui_reexports_input_and_texture_contracts_without_duplicate_entrypoints():
    for name in (
        "CoreError",
        "read_gray_image",
        "normalize_to_uint8",
        "compute_reference_normalization",
        "normalize_with_bounds",
        "sha256_file",
        "ordered_input_manifest",
        "roi_texture_metrics",
        "texture_is_ok",
        "texture_failure_code",
        "require_texture",
        "resolve_code_paths",
    ):
        assert getattr(gui, name) is getattr(core, name)
