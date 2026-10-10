#! /bin/bash
# Entry point dell'AppImage.
# Default: avvia la GUI. Con "cli" come primo argomento usa l'interfaccia a
# riga di comando. Esempi:
#   ./GoProAnamorphic.AppImage                      -> GUI
#   ./GoProAnamorphic.AppImage cli input/ output/   -> CLI
if [ "$1" = "cli" ]; then
    shift
    "{{ python-executable }}" -m gat.cli "$@"
elif [ "$1" = "gui" ]; then
    shift
    "{{ python-executable }}" -m gat.gui "$@"
else
    "{{ python-executable }}" -m gat.gui "$@"
fi
