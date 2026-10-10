"""GUI PySide6 del GoPro Anamorphic Toolkit (Fase 2).

Interfaccia minimale che riusa lo stesso core della Fase 1 (nessuna logica
duplicata): selezione input (cartella o drag-drop di file), rilevamento
automatico dei metadati con avvisi, scelta formato/qualità, checkbox di
stabilizzazione, cartella di output, pulsante Avvia, barra di avanzamento e log.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "PySide6 non è installato. Installa la GUI con:\n"
        "    pip install -e '.[gui]'\n"
    )
    raise

from . import __version__, config, core, metadata
from .config import Settings

# Formati di output offerti: etichetta -> valore di Settings.aspect
FORMATS = [
    ("Automatico (4:3→16:9, 16:9→cinema)", "auto"),
    ("16:9 TV (1920x1080)", "16:9"),
    ("Cinema 2.13:1 (1920x900 ca.)", "2.13:1"),
]
# Qualità: etichetta -> CRF
QUALITIES = [
    ("Alta (CRF 20)", 20),
    ("Media (CRF 22)", 22),
    ("Leggera (CRF 24)", 24),
]


# ---------------------------------------------------------------------------
# Worker in thread separato
# ---------------------------------------------------------------------------

class Worker(QtCore.QObject):
    log = QtCore.Signal(str)
    progress = QtCore.Signal(int, int, str, float)
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, files, out_dir, settings, overwrite):
        super().__init__()
        self._files = files
        self._out_dir = out_dir
        self._settings = settings
        self._overwrite = overwrite

    @QtCore.Slot()
    def run(self) -> None:
        try:
            report = core.run_pipeline(
                self._files,
                self._out_dir,
                self._settings,
                overwrite=self._overwrite,
                log=self.log.emit,
                on_progress=self.progress.emit,
            )
            self.done.emit(report)
        except Exception as exc:  # noqa: BLE001 - mostrato all'utente
            self.failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Finestra principale
# ---------------------------------------------------------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"GoPro Anamorphic Toolkit {__version__}")
        self.setMinimumSize(760, 620)
        self.setAcceptDrops(True)

        self._settings: Settings = config.load_settings()
        self._files: list[Path] = []
        self._thread: QtCore.QThread | None = None
        self._worker: Worker | None = None

        self._build_ui()

    # --- costruzione UI ----------------------------------------------------

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setSpacing(10)

        # Input
        in_box = QtWidgets.QGroupBox("1. File di input")
        in_lay = QtWidgets.QVBoxLayout(in_box)
        btn_row = QtWidgets.QHBoxLayout()
        self.btn_folder = QtWidgets.QPushButton("Scegli cartella…")
        self.btn_files = QtWidgets.QPushButton("Scegli file…")
        self.btn_clear = QtWidgets.QPushButton("Svuota")
        self.btn_folder.clicked.connect(self._choose_folder)
        self.btn_files.clicked.connect(self._choose_files)
        self.btn_clear.clicked.connect(self._clear_files)
        btn_row.addWidget(self.btn_folder)
        btn_row.addWidget(self.btn_files)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch(1)
        in_lay.addLayout(btn_row)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["File", "Risoluzione", "FPS", "Aspect", "Giroscopio"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        in_lay.addWidget(self.table)
        self.drop_hint = QtWidgets.QLabel(
            "Trascina qui cartelle o file .MP4, oppure usa i pulsanti sopra."
        )
        self.drop_hint.setStyleSheet("color: gray;")
        in_lay.addWidget(self.drop_hint)
        root.addWidget(in_box)

        # Opzioni
        opt_box = QtWidgets.QGroupBox("2. Opzioni")
        opt_lay = QtWidgets.QFormLayout(opt_box)

        self.chk_stab = QtWidgets.QCheckBox("Stabilizza con Gyroflow")
        self.chk_stab.setChecked(self._settings.stabilize)
        opt_lay.addRow(self.chk_stab)

        self.cmb_format = QtWidgets.QComboBox()
        for label, _ in FORMATS:
            self.cmb_format.addItem(label)
        opt_lay.addRow("Formato:", self.cmb_format)

        self.cmb_quality = QtWidgets.QComboBox()
        for label, _ in QUALITIES:
            self.cmb_quality.addItem(label)
        self.cmb_quality.setCurrentIndex(1)  # Media
        opt_lay.addRow("Qualità:", self.cmb_quality)

        self.spin_width = QtWidgets.QSpinBox()
        self.spin_width.setRange(640, 3840)
        self.spin_width.setSingleStep(10)
        self.spin_width.setValue(self._settings.width)
        opt_lay.addRow("Larghezza (px):", self.spin_width)

        # Percorso Gyroflow (avanzato, opzionale)
        gyro_row = QtWidgets.QHBoxLayout()
        self.edit_gyroflow = QtWidgets.QLineEdit()
        self.edit_gyroflow.setPlaceholderText("Auto-rilevato (opzionale)")
        if self._settings.gyroflow_bin:
            self.edit_gyroflow.setText(self._settings.gyroflow_bin)
        btn_gyro = QtWidgets.QPushButton("…")
        btn_gyro.setFixedWidth(32)
        btn_gyro.clicked.connect(self._choose_gyroflow)
        gyro_row.addWidget(self.edit_gyroflow)
        gyro_row.addWidget(btn_gyro)
        opt_lay.addRow("Gyroflow:", gyro_row)

        root.addWidget(opt_box)

        # Output
        out_box = QtWidgets.QGroupBox("3. Cartella di output")
        out_lay = QtWidgets.QHBoxLayout(out_box)
        self.edit_output = QtWidgets.QLineEdit()
        self.edit_output.setPlaceholderText("Scegli dove salvare i video finali…")
        btn_out = QtWidgets.QPushButton("Scegli…")
        btn_out.clicked.connect(self._choose_output)
        out_lay.addWidget(self.edit_output)
        out_lay.addWidget(btn_out)
        root.addWidget(out_box)

        # Avvio + progress
        run_row = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Avvia")
        self.btn_start.setMinimumHeight(36)
        self.btn_start.clicked.connect(self._start)
        run_row.addWidget(self.btn_start)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        run_row.addWidget(self.progress, 1)
        root.addLayout(run_row)

        self.lbl_status = QtWidgets.QLabel("Pronto.")
        root.addWidget(self.lbl_status)

        # Log
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setStyleSheet("font-family: monospace; font-size: 11px;")
        root.addWidget(self.log, 1)

    # --- gestione file -----------------------------------------------------

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()]
        self._add_inputs(paths)

    def _choose_folder(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Scegli cartella di input")
        if d:
            self._add_inputs([Path(d)])

    def _choose_files(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Scegli file .MP4", filter="Video GoPro (*.mp4 *.MP4)"
        )
        if files:
            self._add_inputs([Path(f) for f in files])

    def _clear_files(self) -> None:
        self._files = []
        self.table.setRowCount(0)
        self.lbl_status.setText("Pronto.")

    def _add_inputs(self, paths: list[Path]) -> None:
        try:
            found = core.collect_files(paths)
        except core.PipelineError as exc:
            self._warn(str(exc))
            return
        existing = {p.resolve() for p in self._files}
        new = [f for f in found if f.resolve() not in existing]
        if not new:
            self.lbl_status.setText("Nessun nuovo file .MP4 trovato.")
            return
        self._files.extend(new)
        self._refresh_table(new)
        self.lbl_status.setText(f"{len(self._files)} file in coda.")

    def _refresh_table(self, new_files: list[Path]) -> None:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            for f in new_files:
                row = self.table.rowCount()
                self.table.insertRow(row)
                try:
                    info = metadata.probe(f)
                    res = f"{info.width}x{info.height}"
                    fps = f"{info.fps:.2f}"
                    aspect = info.aspect_label
                    gyro = "sì" if info.has_gyro else "NO"
                    warn = not info.is_expected_format or not info.has_gyro
                    tip = "\n".join(info.warnings)
                except metadata.FFprobeError as exc:
                    res = fps = aspect = gyro = "?"
                    warn = True
                    tip = str(exc)
                cells = [f.name, res, fps, aspect, gyro]
                for col, text in enumerate(cells):
                    item = QtWidgets.QTableWidgetItem(text)
                    if warn:
                        item.setForeground(QtGui.QColor("#c0392b"))
                        if tip:
                            item.setToolTip(tip)
                    self.table.setItem(row, col, item)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _choose_output(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Scegli cartella di output")
        if d:
            self.edit_output.setText(d)

    def _choose_gyroflow(self) -> None:
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Scegli l'eseguibile Gyroflow", filter="Gyroflow (*.AppImage gyroflow *)"
        )
        if f:
            self.edit_gyroflow.setText(f)

    # --- avvio elaborazione ------------------------------------------------

    def _collect_settings(self) -> Settings:
        overrides = {
            "stabilize": self.chk_stab.isChecked(),
            "aspect": FORMATS[self.cmb_format.currentIndex()][1],
            "crf": QUALITIES[self.cmb_quality.currentIndex()][1],
            "width": self.spin_width.value(),
            "gyroflow_bin": self.edit_gyroflow.text().strip() or None,
        }
        return self._settings.merged(overrides)

    def _start(self) -> None:
        if not self._files:
            self._warn("Aggiungi almeno un file .MP4.")
            return
        out = self.edit_output.text().strip()
        if not out:
            self._warn("Scegli la cartella di output.")
            return

        settings = self._collect_settings()
        self.log.clear()
        self.progress.setValue(0)
        self._set_running(True)

        self._thread = QtCore.QThread()
        self._worker = Worker(list(self._files), Path(out), settings, overwrite=False)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_start.setText("Elaborazione…" if running else "Avvia")

    @QtCore.Slot(str)
    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    @QtCore.Slot(int, int, str, float)
    def _on_progress(self, i: int, n: int, phase: str, frac: float) -> None:
        # Progresso complessivo: file completati + frazione del file corrente.
        overall = (i + max(0.0, min(1.0, frac))) / n if n else 0.0
        self.progress.setValue(int(overall * 100))
        self.lbl_status.setText(f"[{i + 1}/{n}] {phase}… {int(frac * 100)}%")

    @QtCore.Slot(object)
    def _on_done(self, report) -> None:
        self._finish_thread()
        self.progress.setValue(100)
        msg = f"Completati: {report.ok_count} | Falliti: {len(report.failed)}"
        self.lbl_status.setText(msg)
        self._append_log("\n" + msg)
        for r in report.failed:
            self._append_log(f"  FALLITO {r.source.name}: {r.message}")
        if report.failed:
            self._warn(msg + "\nVedi il log per i dettagli.")
        else:
            QtWidgets.QMessageBox.information(self, "Fatto", msg)

    @QtCore.Slot(str)
    def _on_failed(self, message: str) -> None:
        self._finish_thread()
        self.lbl_status.setText("Errore.")
        self._append_log(f"ERRORE: {message}")
        self._warn(message)

    def _finish_thread(self) -> None:
        self._set_running(False)
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    def _warn(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Attenzione", message)


def main(argv: list[str] | None = None) -> int:
    app = QtWidgets.QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("GoPro Anamorphic Toolkit")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
