#! /bin/bash
# AppImage entry point.
# Default: start the GUI. With "cli" as first argument, use the command line.
# Examples:
#   ./GoProAnamorphic-x86_64.AppImage                      -> GUI
#   ./GoProAnamorphic-x86_64.AppImage cli input/ output/   -> CLI
if [ "$1" = "cli" ]; then
    shift
    "{{ python-executable }}" -m gat.cli "$@"
elif [ "$1" = "gui" ]; then
    shift
    "{{ python-executable }}" -m gat.gui "$@"
else
    "{{ python-executable }}" -m gat.gui "$@"
fi
