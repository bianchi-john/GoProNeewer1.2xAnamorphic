"""Integration tests of the Summer look rendering (require ffmpeg)."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gat import config, core  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _stats(png: Path) -> dict[str, float]:
    """Average U, V and saturation of an image, measured by ffmpeg signalstats."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(png), "-vf",
         "format=yuv444p,signalstats,metadata=print:file=-", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    keys = {"UAVG": "u", "VAVG": "v", "SATAVG": "sat"}
    return {
        short: float(re.search(rf"lavfi\.signalstats\.{key}=([\d.]+)", out).group(1))
        for key, short in keys.items()
    }


def test_preview_look_is_warmer_and_more_saturated(tmp_path):
    sample = config.preview_samples()["Beach"]
    before, after = tmp_path / "before.png", tmp_path / "after.png"
    before.write_bytes(core.render_look_preview(sample, 0, width=320))
    after.write_bytes(core.render_look_preview(sample, 100, width=320))
    b, a = _stats(before), _stats(after)
    assert a["sat"] > b["sat"]  # more saturated
    assert a["u"] < b["u"]  # less blue
    assert a["v"] > b["v"]  # more red


def test_preview_is_png(tmp_path):
    data = core.render_look_preview(config.preview_samples()["Mountain lake"], 50, width=200)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
