"""Tests of the Gyroflow wrapper using a fake Gyroflow executable."""

import json
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gat import config, gyroflow  # noqa: E402

FAKE_OK = """#!/bin/bash
# Fake Gyroflow: print the harmless AMD noise, then write <stem>_stabilized.mp4.
video="$1"; preset="$3"
echo "Failed to initialize OpenCL Platform::list: Error retrieving platform list"
echo "   12: <unknown>"
echo "Cannot load libcuda.so.1"
echo "[INFO] Applying preset $preset"
echo "[INFO] Initialized wgpu for (1352, 760)"
grep -q calibration_file "$preset" || exit 3
touch "${video%.*}_stabilized.mp4"
echo "[INFO] Done in 1.5s"
"""

FAKE_FAIL = """#!/bin/bash
echo "Failed to initialize OpenCL Platform::list"
echo "[ERROR] Something really went wrong"
exit 1
"""


def _fake(tmp_path: Path, body: str) -> str:
    exe = tmp_path / "fake-gyroflow"
    exe.write_text(body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


@pytest.fixture
def video(tmp_path):
    v = tmp_path / "GX010050.MP4"
    v.write_bytes(b"fake")
    return v


def test_success_collapses_harmless_messages(tmp_path, video):
    logs: list[str] = []
    res = gyroflow.run(video, config.default_lens_profile(),
                       gyroflow_bin=_fake(tmp_path, FAKE_OK), log=logs.append)
    assert res.output == tmp_path / "GX010050_stabilized.mp4"
    assert res.done_seconds == 1.5 and res.used_wgpu
    text = "\n".join(logs)
    assert "ignored 3 harmless GPU-backend messages" in text
    assert "OpenCL" not in text.replace("OpenCL/CUDA/AMF", "")  # noise not echoed
    assert "[gyroflow]" not in text  # Gyroflow's own lines hidden unless verbose
    assert not list(tmp_path.glob("*.gyroflow"))  # temporary preset removed


def test_verbose_echoes_gyroflow_output(tmp_path, video):
    logs: list[str] = []
    gyroflow.run(video, config.default_lens_profile(),
                 gyroflow_bin=_fake(tmp_path, FAKE_OK), log=logs.append, verbose=True)
    assert any("[gyroflow] [INFO] Applying preset" in line for line in logs)


def test_failure_shows_tail_and_raises(tmp_path, video):
    logs: list[str] = []
    with pytest.raises(gyroflow.GyroflowError):
        gyroflow.run(video, config.default_lens_profile(),
                     gyroflow_bin=_fake(tmp_path, FAKE_FAIL), log=logs.append)
    assert any("Something really went wrong" in line for line in logs)


def test_preset_has_absolute_profile_path(tmp_path):
    preset = gyroflow.write_preset(config.default_lens_profile(), dest_dir=tmp_path)
    data = json.loads(preset.read_text())
    assert Path(data["calibration_file"]).is_absolute()
    assert data["output"] == {"codec": "H.264/AVC", "bitrate": 100}


def test_missing_gyroflow_is_reported(tmp_path, video):
    with pytest.raises(gyroflow.GyroflowError, match="Gyroflow not found"):
        gyroflow.run(video, config.default_lens_profile(),
                     gyroflow_bin=str(tmp_path / "does-not-exist"))
