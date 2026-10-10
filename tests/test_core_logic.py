"""Tests of the pure logic (no ffmpeg/Gyroflow required)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gat import cli, config, core, gyroflow, metadata  # noqa: E402
from gat.metadata import MediaInfo  # noqa: E402


def _info(w, h, gyro=True):
    return MediaInfo(
        path=Path("x.mp4"), width=w, height=h, fps=59.94,
        duration=10.0, codec="hevc", has_gyro=gyro,
    )


# --- zoom_factor -----------------------------------------------------------

def test_zoom_stabilized_is_one():
    assert core.zoom_factor("auto", stabilized=True) == 1.0


def test_zoom_auto_no_stab():
    assert core.zoom_factor("auto", stabilized=False) == 1.2


def test_zoom_explicit():
    assert core.zoom_factor("1.15", stabilized=True) == 1.15


# --- output_dimensions (full resolution, no downscale) ---------------------

def test_output_dimensions_stabilized_fullres():
    # 2704x1520 desqueezed 1.2x, zoom 1.0 -> 3244x1520 (cinema ~2.13:1)
    w, h = core.output_dimensions(2704, 1520, squeeze=1.2, zoom=1.0)
    assert (w, h) == (3244, 1520)


def test_output_dimensions_no_stab_vignette_crop():
    # zoom 1.2 trims the vignetting; still no downscale
    w, h = core.output_dimensions(2704, 1520, squeeze=1.2, zoom=1.2)
    assert (w, h) == (2702, 1266)
    assert w % 2 == 0 and h % 2 == 0


# --- build_vf ----------------------------------------------------------------

def test_build_vf_no_downscale():
    vf = core.build_vf(1.2, 1.0)
    assert "scale=trunc(iw*1.2/2)*2:ih" in vf
    assert "crop=trunc(iw/1.0/2)*2:trunc(ih/1.0/2)*2" in vf
    assert vf.count("scale=") == 1  # no final fixed-size scale
    assert "lutyuv" not in vf  # look off by default


def test_build_vf_with_look_appends_filter_last():
    vf = core.build_vf(1.2, 1.0, look_intensity=50)
    assert vf.split(",crop=")[1].count("lutyuv=") == 1
    assert vf.rstrip("'").endswith("minval,maxval)")


# --- Summer look -----------------------------------------------------------

def test_look_off_at_zero():
    assert core.look_filter(0) is None
    assert core.look_filter(-5) is None


def test_look_scales_with_intensity_and_clamps():
    half = core.look_filter(50)
    full = core.look_filter(100)
    over = core.look_filter(250)
    assert "*1.1500" in half  # +15% saturation at 50
    assert "*1.3000" in full  # +30% saturation at 100
    assert over == full  # clamped to 100


def test_look_is_warm():
    f = core.look_filter(100)
    u_expr, v_expr = f.split(":v=")
    assert "-0.0220*" in u_expr  # U (blue) pushed down
    assert "+0.0160*" in v_expr  # V (red) pushed up


def test_effective_look_intensity():
    s = config.Settings()
    assert core.effective_look_intensity(s) == 0  # off by default
    s.look, s.look_intensity = True, 70
    assert core.effective_look_intensity(s) == 70


# --- gyroflow harmless-message detection ----------------------------------

def test_benign_patterns():
    assert gyroflow.is_benign("Failed to initialize OpenCL Platform::list ...")
    assert gyroflow.is_benign("Cannot load libcuda.so.1")
    assert gyroflow.is_benign("libamfrt64.so.1 not found")
    assert gyroflow.is_benign("   12: <unknown>")
    assert not gyroflow.is_benign("Initialized wgpu for AMD")
    assert not gyroflow.is_benign("Done in 42.0s")


# --- output_name -----------------------------------------------------------

def test_output_name():
    assert core.output_name(Path("GX010050.MP4"), 3244, 1520) == (
        "GX010050_anamorphic_3244x1520.mp4"
    )


# --- format support (2.7K 16:9 only) ---------------------------------------

def test_supported_only_16by9_2k7():
    assert _info(2704, 1520).is_supported is True
    assert _info(2704, 2028).is_supported is False  # 4:3
    assert _info(1920, 1080).is_supported is False  # 16:9 but not 2.7K


def test_is_16by9():
    assert _info(2704, 1520).is_16by9 is True
    assert _info(2704, 2028).is_16by9 is False


def test_validate_flags_4by3():
    warns = metadata.validate(_info(2704, 2028))
    assert any("not 16:9" in w.lower() for w in warns)


# --- resources ---------------------------------------------------------------

def test_bundled_resources_exist():
    assert config.default_lens_profile() is not None
    assert set(config.preview_samples()) == set(config.PREVIEW_SAMPLES)


# --- CLI -----------------------------------------------------------------------

def test_cli_look_options():
    args = cli.build_parser().parse_args(["in", "out", "--summer-look", "--look-intensity", "60"])
    assert cli._overrides_from_args(args)["look"] is True
    assert cli._overrides_from_args(args)["look_intensity"] == 60


def test_cli_rejects_out_of_range_intensity(capsys):
    import pytest
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["in", "out", "--look-intensity", "150"])


# --- collect_files ---------------------------------------------------------

def test_collect_files_dedup_and_mixed(tmp_path):
    (tmp_path / "a.MP4").write_bytes(b"")
    (tmp_path / "b.mp4").write_bytes(b"")
    (tmp_path / "note.txt").write_bytes(b"")
    files = core.collect_files([tmp_path, tmp_path / "a.MP4"])
    assert sorted(p.name for p in files) == ["a.MP4", "b.mp4"]


def test_collect_files_single_path(tmp_path):
    (tmp_path / "x.MP4").write_bytes(b"")
    assert [p.name for p in core.collect_files(tmp_path)] == ["x.MP4"]
