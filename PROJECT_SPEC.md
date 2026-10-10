# GoPro Anamorphic Toolkit — Project specification

> Starting document for Claude Code. It describes what to build, in which
> phases, and all the technical details already verified in the field. Read it
> all before starting. Proceed **in phases**, not all at once: complete and test
> one phase before moving to the next.
>
> This is the English translation of the original specification. Decisions
> taken later during development are listed in [section 9](#9-later-revisions)
> and take precedence over the original text where they differ.

## 1. Goal

A Linux tool with a simple graphical interface that takes the original video
files of a **GoPro HERO11 Black** shot with a **Neewer LS-56 1.2x anamorphic
lens** (unofficial) and produces ready-to-use videos:

1. Anamorphic **desqueeze** (1.2x horizontal factor) — always.
2. **Stabilization** with Gyroflow using a lens profile **calibrated by the
   user** — optional, switchable from the interface.
3. **Export** to a lightweight format (default 1080p H.265) suited to TVs.

The tool does NOT use the GoPro's internal stabilization (HyperSmooth): it uses
the raw gyroscope data contained in the file (GPMF) + Gyroflow. This is
intentional and correct: with the unofficial lens HyperSmooth produces wobble,
while Gyroflow with a calibrated profile gives a better result.

The project must be publishable as a repository and usable by others.

## 2. Technical context already verified

These facts have been verified in the field and are taken for granted:

- **Recommended shooting format**: 2.7K (2704x1520 for 16:9, 2704x2028 for
  4:3), **Wide** lens, HyperSmooth **off**. In Wide the image has fisheye
  distortion that Gyroflow corrects with the profile.
- **Lens squeeze factor**: 1.2x horizontal, 1.0 vertical.
- **Gyro data**: contained in the **GPMF** track of the original MP4 file
  (handler `GoPro MET`). It is lost if the file goes through apps/editors that
  re-encode it. ALWAYS use the original files from the SD card.
- **Gyroflow**: used as an external executable (AppImage) through its CLI.
  Typical command: `Gyroflow.AppImage <video> --preset <file.gyroflow> -f`.
  It writes a `<name>_stabilized.mp4` file next to the input.
- **Calibrated lens profile**: `.json` file produced by the Gyroflow Lens
  Calibrator. During calibration, Input horizontal stretch = 1.2. Reprojection
  error obtained: ~1.27 (good). The profile is specific to the HERO11 + Neewer +
  settings combination.
- **Gyroflow preset** (`neewer.gyroflow`): JSON giving the output codec/bitrate
  and the path of the `calibration_file`. Working example:
  ```json
  {
    "version": 2,
    "calibration_file": "/absolute/path/neewer_lens.json",
    "output": {"codec": "H.264/AVC", "bitrate": 100}
  }
  ```
- **Known harmless bug**: on AMD hardware (e.g. ThinkPad E485, Ryzen 2700U)
  Gyroflow repeatedly prints `Failed to initialize OpenCL Platform::list ...`
  and `Cannot load libcuda.so.1` / `libamfrt64.so.1`. These are NOT fatal
  errors: Gyroflow falls back to `wgpu` (line `Initialized wgpu for ...`) and
  completes the render. The tool must ignore these messages and judge success
  from the presence of the `_stabilized.mp4` file and the `Done in <time>s` line.
- **Desqueeze + crop + encode pipeline** (already working in ffmpeg):
  `scale=iw*1.2:ih` (desqueeze) → `crop` to the final format → `scale` to
  1080p → `libx265 -crf 22 -preset medium -tag:v hvc1`.
- **Order of operations**: Gyroflow FIRST (stabilizes + corrects the lens on the
  original file with GPMF), then ffmpeg on the stabilized file for desqueeze,
  crop and export. The desqueeze must happen AFTER Gyroflow.
- When stabilizing with Gyroflow NO extra anti-vignetting crop is needed
  (ZOOM=1.0): Gyroflow already crops the edges. Without stabilization, 4:3 Wide
  needs a ~1.3x crop to remove the vignetting, 16:9 ~1.2x.

### Point to verify during development
Gyroflow also loads lens profiles from `~/.local/share/Gyroflow/lens_profiles`.
It must be verified that the `calibration_file` given in the preset is actually
applied to the render (and not a default profile). Add a test that compares the
stabilized output with and without the profile, or that logs which profile was
loaded.

## 3. Output formats

- From **4:3** (2704x2028): desqueeze 1.2x → crop to 16:9 → 1080p. Uses the
  whole sensor, more margin for stabilization.
- From **16:9** (2704x1520): desqueeze 1.2x → ~2.13:1 result (cinematic) →
  export at 1920 width (e.g. 1920x900).
- Both cases configurable (aspect ratio and final width).

## 4. Interface (simple)

Minimum interface requirements:
- Selection of an input folder (or drag & drop of files).
- Automatic detection of each file's settings (resolution, fps, GPMF presence,
  aspect) via ffprobe/exiftool, with a warning when a file is not in the
  expected format (e.g. not 2.7K, or missing gyro).
- "Stabilize with Gyroflow" checkbox (on by default).
- Choice of output format (16:9 TV / 2.13:1 cinema) and quality.
- Start button, progress bar, log.
- Selectable output folder.

Keep the interface minimal and clean. Clarity first, not options.

## 5. Recommended architecture (in phases)

### Phase 1 — Core CLI (clean rewrite of the existing script)
- Language: **Python 3**.
- Module that: scans the input, reads metadata, validates the format, calls
  Gyroflow (when requested), runs the ffmpeg pipeline, writes the output.
- Configuration via CLI arguments + config file.
- The calibrated lens profile (`neewer_lens.json`) must be **included in the
  repository** as the default resource, and the preset generated on the fly
  with the correct absolute path at runtime (do not hard-code `/home/john/...`).
- OpenCL bug handling: do not treat Gyroflow's stderr as failure; check success
  from the produced file.
- Tests on real files (see section 7).

### Phase 2 — GUI
- Recommended options, chosen for ease of AppImage packaging:
  - **PySide6/Qt** (complete, packages well) — recommended.
  - Alternatives: GTK (PyGObject), or a local web UI (heavier).
- The GUI calls the same core as Phase 1 (no duplicated logic).

### Phase 3 — AppImage packaging
- Package the Python app as a Linux **AppImage** (tools such as
  `python-appimage`, `appimage-builder`, or `linuxdeploy` + conda/venv).
- **Gyroflow must NOT be included in the AppImage.** It is a requirement: the
  user downloads their own `Gyroflow.AppImage` and points to it in the settings
  (or it is searched in well-known locations). Document this clearly in the
  README.
- The default calibrated lens profile may be included.

## 6. Proposed repository structure

```
gopro-anamorphic-toolkit/
├── README.md
├── LICENSE                 (suggest MIT or GPLv3; ask the user)
├── .gitignore              (must exclude the gopro/ test folder and outputs)
├── PROJECT_SPEC.md         (this file)
├── src/
│   └── gat/
│       ├── __init__.py
│       ├── core.py         (pipeline: scan, validate, gyroflow, ffmpeg)
│       ├── metadata.py     (ffprobe/exiftool, GPMF and format detection)
│       ├── gyroflow.py     (Gyroflow CLI wrapper, OpenCL bug handling)
│       ├── cli.py          (command-line entry point)
│       └── gui.py          (Phase 2)
├── resources/
│   └── neewer_lens.json    (default calibrated lens profile)
├── tests/
│   └── ...                 (see section 7)
└── packaging/
    └── ...                 (AppImage scripts, Phase 3)
```

## 7. Included test material

The root contains a **`gopro/`** folder with real material for testing during
development:
- `gopro/169/GX010050.MP4` — 16:9 clip, 2.7K, Wide, with strong intentional
  shake (useful to test stabilization).
- `gopro/43/GX010049.MP4` — 4:3 clip, 2.7K, Wide.
- `gopro/calibration/GX010051.MP4` — checkerboard video.
- `gopro/neewer_lens.json` — calibrated lens profile (copy it into the
  resources).
- `gopro/Gyroflow.AppImage` — Gyroflow executable for testing (not committed).
- `gopro/gopro_anamorphic.sh` — the original bash script, to be used as a
  reference for the logic (NOT as final code).

Use these files to verify each phase. The test clips may be published in the
repo (no sensitive content), but given their size consider git-lfs or a
separate download link.

## 8. Final notes for Claude Code

- Proceed in blocks, with frequent commits and clear messages.
- Do not hard-code the user's absolute paths: everything relative or
  configurable.
- Write a clear README with: requirements (incl. the Gyroflow AppImage and
  ffmpeg), installation, usage, how to calibrate your own lens, known
  limitations.
- Document the AMD OpenCL bug in the README as "expected behavior".
- Ask the user to confirm: project name, license, and whether to publish the
  test clips.

## 9. Later revisions

Decisions taken with the user during development (they override the sections
above where they differ):

- **Project setup**: repository `GoProNeewer1.2xAnamorphic`, **MIT** license,
  public, test clips published via **Git LFS**.
- **16:9 only**: the calibrated lens profile is valid only for 2.7K 16:9 Wide,
  so 4:3 cannot be stabilized correctly. The tool processes only 2704x1520
  clips; any other file is flagged in the file list and **skipped**. The format
  choice was removed (supersedes section 3 and the 4:3 parts of section 2).
- **Full-resolution, high-quality export**: no 1080p downscale. Output at the
  full desqueezed resolution (~3244x1520), H.265 CRF 18, preset slow, `hvc1`.
  No "quality" presets in the UI (CRF/preset live in Advanced options).
- **Explicit stabilization**: the log states for every file whether
  stabilization was applied.
- **Summer look**: optional, off by default — a touch more saturation and warmth
  with adjustable intensity and a before/after preview (bundled CC0 sample
  images or a frame of the user's own clip). The same ffmpeg filter is used for
  the preview and the export.
- **Simplified, modern GUI**: dark theme, prominent Stabilize toggle, Advanced
  options collapsed by default, always-visible Start bar.
- **Resources** live in `src/gat/resources/` (shipped with the package and the
  AppImage) instead of a top-level `resources/` folder.
- **Everything in English**: code, comments, UI, CLI, logs and documentation.
