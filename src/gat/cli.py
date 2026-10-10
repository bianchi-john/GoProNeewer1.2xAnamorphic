"""Command-line entry point of the GoPro Anamorphic Toolkit.

Examples::

    # Stabilize + desqueeze at full resolution (high-quality defaults)
    gat input/ output/

    # Desqueeze only (no Gyroflow)
    gat input/ output/ --no-stabilize

    # Add the Summer look (a touch more saturation and warmth)
    gat input/ output/ --summer-look --look-intensity 60

    # Inspect files only (metadata and validation)
    gat input/ --probe
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, config, core, metadata
from .config import Settings


def _print(msg: str) -> None:
    print(msg, flush=True)


def _intensity(value: str) -> int:
    v = int(value)
    if not 0 <= v <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return v


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gat",
        description=(
            "GoPro Anamorphic Toolkit — Gyroflow stabilization + 1.2x anamorphic "
            "desqueeze + full-resolution H.265 export for GoPro HERO11 2.7K 16:9 "
            "clips shot with the Neewer LS-56 lens."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", help="Input folder (or single .MP4 file)")
    p.add_argument("output", nargs="?", help="Output folder (not needed with --probe)")

    p.add_argument("--probe", action="store_true",
                   help="Inspect only: print metadata and validation, process nothing")
    p.add_argument("--config", help="JSON config file (default: ~/.config/gat/config.json)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    stab = p.add_argument_group("stabilization")
    g = stab.add_mutually_exclusive_group()
    g.add_argument("--stabilize", dest="stabilize", action="store_true", default=None,
                   help="Stabilize with Gyroflow (on by default)")
    g.add_argument("--no-stabilize", dest="stabilize", action="store_false",
                   help="Disable stabilization (desqueeze + export only)")
    stab.add_argument("--gyroflow", dest="gyroflow_bin", help="Path to the Gyroflow executable/AppImage")
    stab.add_argument("--calibration", dest="calibration_file",
                      help="Lens profile .json (default: bundled profile)")
    stab.add_argument("--gyroflow-bitrate", type=int, help="Bitrate (Mbps) of the Gyroflow intermediate file")

    look = p.add_argument_group("summer look")
    lg = look.add_mutually_exclusive_group()
    lg.add_argument("--summer-look", dest="look", action="store_true", default=None,
                    help="Add a touch more saturation and warmth (off by default)")
    lg.add_argument("--no-summer-look", dest="look", action="store_false",
                    help="Disable the Summer look")
    look.add_argument("--look-intensity", dest="look_intensity", type=_intensity,
                      help="Summer look intensity 0-100 (default 50; even 100 stays subtle)")

    out = p.add_argument_group("desqueeze / export (full resolution, high quality)")
    out.add_argument("--squeeze", type=float, help="Horizontal anamorphic factor (default 1.2)")
    out.add_argument("--zoom", help="Anti-vignetting crop: auto | factor (e.g. 1.2)")
    out.add_argument("--crf", type=int, help="H.265 quality (lower = better; default 18)")
    out.add_argument("--preset", help="x265 preset (ultrafast..placebo; default slow)")

    p.add_argument("--overwrite", action="store_true", help="Process again even if the output exists")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Also log the exact ffmpeg/Gyroflow commands and Gyroflow's output")
    p.add_argument("--save-config", action="store_true",
                   help="Save the current options to the config file and exit")
    return p


def _overrides_from_args(args: argparse.Namespace) -> dict:
    keys = [
        "stabilize", "gyroflow_bin", "calibration_file", "gyroflow_bitrate",
        "look", "look_intensity", "squeeze", "zoom", "crf", "preset",
    ]
    return {k: getattr(args, k) for k in keys if getattr(args, k) is not None}


def _do_probe(input_path: str) -> int:
    try:
        files = core.scan_input(input_path)
    except core.PipelineError as exc:
        _print(f"Error: {exc}")
        return 2
    if not files:
        _print(f"No .MP4 files in {input_path}")
        return 1
    rc = 0
    for f in files:
        try:
            info = metadata.probe(f)
        except metadata.FFprobeError as exc:
            _print(f"{f.name}: ERROR {exc}")
            rc = 1
            continue
        _print(info.summary())
        for w in info.warnings:
            _print(f"  ! {w}")
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        base = config.load_settings(args.config)
    except ValueError as exc:
        _print(f"Config error: {exc}")
        return 2
    settings: Settings = base.merged(_overrides_from_args(args))
    # Asking for an intensity implies turning the look on.
    if args.look_intensity is not None and args.look is None:
        settings.look = True

    if args.save_config:
        path = config.save_settings(settings, args.config)
        _print(f"Config saved to {path}")
        return 0

    if args.probe:
        return _do_probe(args.input)

    if not args.output:
        parser.error("the output folder is required (or use --probe)")

    look_k = core.effective_look_intensity(settings)
    _print(f"gat {__version__}")
    _print(
        f"Stabilization: {'ON' if settings.stabilize else 'OFF'} | "
        f"Summer look: {str(look_k) + '%' if look_k else 'OFF'} | "
        f"full-res desqueeze {settings.squeeze}x | H.265 CRF {settings.crf} "
        f"preset {settings.preset} | 16:9 2.7K only"
    )

    try:
        report = core.run_pipeline(args.input, args.output, settings,
                                   overwrite=args.overwrite, log=_print,
                                   verbose=args.verbose)
    except (core.PipelineError, metadata.FFprobeError) as exc:
        _print(f"Error: {exc}")
        return 2

    _print("")
    _print(f"Processed: {report.ok_count} | Skipped: {report.skipped_count} | "
           f"Failed: {len(report.failed)}")
    for r in report.failed:
        _print(f"  FAILED {r.source.name}: {r.message}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
