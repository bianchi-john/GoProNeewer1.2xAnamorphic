"""Entry point a riga di comando del GoPro Anamorphic Toolkit.

Esempi::

    # Stabilizza + desqueeze, formato automatico in base all'input
    gat input/ output/

    # Solo desqueeze (niente Gyroflow)
    gat input/ output/ --no-stabilize

    # Forza formato cinema 2.13:1 a 1920 di larghezza
    gat input/ output/ --aspect 2.13:1 --width 1920

    # Solo ispezione dei file (metadati e validazione)
    gat input/ --probe
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config, core, metadata
from .config import Settings


def _print(msg: str) -> None:
    print(msg, flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gat",
        description=(
            "GoPro Anamorphic Toolkit — stabilizzazione (Gyroflow) + desqueeze "
            "anamorfico 1.2x + export H.265 per clip GoPro HERO11 + Neewer LS-56."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", help="Cartella (o singolo file .MP4) di input")
    p.add_argument(
        "output", nargs="?", help="Cartella di output (non serve con --probe)"
    )

    p.add_argument(
        "--probe",
        action="store_true",
        help="Solo analisi: stampa metadati e validazione, non elabora nulla",
    )
    p.add_argument("--config", help="File di config JSON (default: ~/.config/gat/config.json)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    stab = p.add_argument_group("stabilizzazione")
    g = stab.add_mutually_exclusive_group()
    g.add_argument(
        "--stabilize",
        dest="stabilize",
        action="store_true",
        default=None,
        help="Attiva la stabilizzazione Gyroflow (default attivo)",
    )
    g.add_argument(
        "--no-stabilize",
        dest="stabilize",
        action="store_false",
        help="Disattiva la stabilizzazione (solo desqueeze/export)",
    )
    stab.add_argument("--gyroflow", dest="gyroflow_bin", help="Percorso dell'eseguibile/AppImage Gyroflow")
    stab.add_argument("--calibration", dest="calibration_file", help="Profilo lente .json (default: incluso)")
    stab.add_argument("--gyroflow-bitrate", type=int, help="Bitrate (Mbps) output intermedio Gyroflow")

    out = p.add_argument_group("desqueeze / export (piena risoluzione, alta qualità)")
    out.add_argument("--squeeze", type=float, help="Fattore anamorfico orizzontale (default 1.2)")
    out.add_argument("--zoom", help="Ritaglio anti-vignettatura: auto | fattore (es. 1.2)")
    out.add_argument("--crf", type=int, help="Qualità H.265 (più basso = migliore; default 18)")
    out.add_argument("--preset", help="Preset x265 (ultrafast..placebo; default slow)")

    p.add_argument("--overwrite", action="store_true", help="Rielabora anche se l'output esiste")
    p.add_argument(
        "--save-config",
        action="store_true",
        help="Salva le opzioni correnti nel file di config e termina",
    )
    return p


def _overrides_from_args(args: argparse.Namespace) -> dict:
    keys = [
        "stabilize",
        "gyroflow_bin",
        "calibration_file",
        "gyroflow_bitrate",
        "squeeze",
        "zoom",
        "crf",
        "preset",
    ]
    return {k: getattr(args, k) for k in keys if getattr(args, k) is not None}


def _do_probe(input_path: str) -> int:
    try:
        files = core.scan_input(input_path)
    except core.PipelineError as exc:
        _print(f"Errore: {exc}")
        return 2
    if not files:
        _print(f"Nessun file .MP4 in {input_path}")
        return 1
    rc = 0
    for f in files:
        try:
            info = metadata.probe(f)
        except metadata.FFprobeError as exc:
            _print(f"{f.name}: ERRORE {exc}")
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
        _print(f"Errore config: {exc}")
        return 2
    settings: Settings = base.merged(_overrides_from_args(args))

    if args.save_config:
        path = config.save_settings(settings, args.config)
        _print(f"Config salvata in {path}")
        return 0

    if args.probe:
        return _do_probe(args.input)

    if not args.output:
        parser.error("serve la cartella di output (oppure usa --probe)")

    _print(f"gat {__version__}")
    _print(
        f"Stabilization: {'ON' if settings.stabilize else 'OFF'} | "
        f"full-res desqueeze {settings.squeeze}x | H.265 CRF {settings.crf} "
        f"preset {settings.preset} | 16:9 2.7K only"
    )

    try:
        report = core.run_pipeline(
            args.input,
            args.output,
            settings,
            overwrite=args.overwrite,
            log=_print,
        )
    except (core.PipelineError, metadata.FFprobeError) as exc:
        _print(f"Errore: {exc}")
        return 2

    _print("")
    _print(f"Completati: {report.ok_count} | Falliti: {len(report.failed)}")
    for r in report.failed:
        _print(f"  FALLITO {r.source.name}: {r.message}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
