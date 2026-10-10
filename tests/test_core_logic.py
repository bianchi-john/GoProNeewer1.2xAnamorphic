"""Test della logica pura (nessuna dipendenza da ffmpeg/Gyroflow)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gat import core, gyroflow, metadata  # noqa: E402
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
    # 2704x1520 desqueeze 1.2x, zoom 1.0 -> ~3244x1520 (cinema ~2.13:1)
    w, h = core.output_dimensions(2704, 1520, squeeze=1.2, zoom=1.0)
    assert w == 3244 and h == 1520
    assert w % 2 == 0 and h % 2 == 0


def test_output_dimensions_no_stab_vignette_crop():
    # zoom 1.2 riduce per togliere la vignettatura, ma resta piena qualità
    w, h = core.output_dimensions(2704, 1520, squeeze=1.2, zoom=1.2)
    assert w == 2702 and h == 1266
    assert w % 2 == 0 and h % 2 == 0


# --- build_vf (desqueeze + crop anti-vignettatura, NO downscale) -----------

def test_build_vf_no_downscale():
    vf = core.build_vf(1.2, 1.0)
    assert "scale=trunc(iw*1.2/2)*2:ih" in vf
    assert "crop=trunc(iw/1.0/2)*2:trunc(ih/1.0/2)*2" in vf
    # nessun scale finale a risoluzione fissa
    assert vf.count("scale=") == 1


# --- gyroflow benign detection --------------------------------------------

def test_benign_patterns():
    assert gyroflow.is_benign("Failed to initialize OpenCL Platform::list ...")
    assert gyroflow.is_benign("Cannot load libcuda.so.1")
    assert gyroflow.is_benign("libamfrt64.so.1 not found")
    assert not gyroflow.is_benign("Initialized wgpu for AMD")
    assert not gyroflow.is_benign("Done in 42.0s")


# --- output_name -----------------------------------------------------------

def test_output_name():
    assert core.output_name(Path("GX010050.MP4"), 3244, 1520) == (
        "GX010050_anamorphic_3244x1520.mp4"
    )


# --- format support (16:9 2.7K only) --------------------------------------

def test_supported_only_16by9_2k7():
    assert _info(2704, 1520).is_supported is True
    assert _info(2704, 2028).is_supported is False  # 4:3
    assert _info(1920, 1080).is_supported is False  # 16:9 ma non 2.7K


def test_is_16by9():
    assert _info(2704, 1520).is_16by9 is True
    assert _info(2704, 2028).is_16by9 is False


def test_validate_skips_4by3():
    warns = metadata.validate(_info(2704, 2028))
    assert any("not 16:9" in w.lower() or "skipped" in w.lower() for w in warns)


# --- collect_files ---------------------------------------------------------

def test_collect_files_dedup_and_mixed(tmp_path):
    (tmp_path / "a.MP4").write_bytes(b"")
    (tmp_path / "b.mp4").write_bytes(b"")
    (tmp_path / "note.txt").write_bytes(b"")
    files = core.collect_files([tmp_path, tmp_path / "a.MP4"])
    names = sorted(p.name for p in files)
    assert names == ["a.MP4", "b.mp4"]


def test_collect_files_single_path(tmp_path):
    (tmp_path / "x.MP4").write_bytes(b"")
    files = core.collect_files(tmp_path)
    assert [p.name for p in files] == ["x.MP4"]
