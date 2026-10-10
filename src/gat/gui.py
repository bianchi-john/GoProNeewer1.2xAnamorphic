"""PySide6 GUI for the GoPro Anamorphic Toolkit (Phase 2).

Minimal, modern dark-themed interface that reuses the exact same core as the
CLI (no processing logic is duplicated here). The tool targets ONE format only:
GoPro HERO11 2.7K **16:9** clips. Anything else is flagged in the file list and
skipped, never processed.

Default view shows only the essentials: input + file list, a prominent
Stabilize toggle, output folder, and the Start button with progress and log.
Everything advanced (Gyroflow path, encoder settings) lives in a collapsible
"Advanced options" section, hidden by default.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "PySide6 is not installed. Install the GUI with:\n"
        "    pip install -e '.[gui]'\n"
    )
    raise

from . import __version__, config, core, metadata
from .config import Settings

# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------

ACCENT = "#4f8cff"
ACCENT_HOVER = "#6ba0ff"
OK_GREEN = "#3ecf8e"
WARN = "#f0a842"
BAD = "#f06a6a"

STYLESHEET = f"""
QWidget {{
    background: #1b1e24;
    color: #e6e9ef;
    font-family: "Inter", "Segoe UI", "Cantarell", sans-serif;
    font-size: 13px;
}}
#Header {{ background: transparent; }}
#Title {{ font-size: 20px; font-weight: 700; color: #ffffff; }}
#Subtitle {{ color: #9aa4b2; font-size: 12px; }}

QFrame#Card {{
    background: #242933;
    border: 1px solid #333a47;
    border-radius: 12px;
}}
QLabel#SectionLabel {{ color: #9aa4b2; font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 1px; }}

QPushButton {{
    background: #2f3643;
    border: 1px solid #3c4453;
    border-radius: 8px;
    padding: 8px 14px;
    color: #e6e9ef;
}}
QPushButton:hover {{ background: #39414f; }}
QPushButton:pressed {{ background: #2a303b; }}

QPushButton#Primary {{
    background: {ACCENT};
    border: none;
    color: white;
    font-size: 15px;
    font-weight: 700;
    padding: 12px 20px;
    border-radius: 10px;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:disabled {{ background: #39414f; color: #8a93a2; }}

QPushButton#Link {{
    background: transparent; border: none; color: #9aa4b2;
    padding: 4px 2px; text-align: left;
}}
QPushButton#Link:hover {{ color: #e6e9ef; }}

QLineEdit, QSpinBox, QComboBox {{
    background: #1b1e24;
    border: 1px solid #3c4453;
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}

QTableWidget {{
    background: #1b1e24;
    border: 1px solid #333a47;
    border-radius: 8px;
    gridline-color: #2a303b;
}}
QHeaderView::section {{
    background: #242933; color: #9aa4b2; border: none;
    border-bottom: 1px solid #333a47; padding: 8px; font-weight: 600;
}}
QTableWidget::item {{ padding: 6px; border-bottom: 1px solid #22272f; }}

QPlainTextEdit {{
    background: #15171c;
    border: 1px solid #333a47;
    border-radius: 8px;
    font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace;
    font-size: 11px;
    color: #c7cddb;
}}

QProgressBar {{
    background: #1b1e24; border: 1px solid #3c4453; border-radius: 8px;
    height: 18px; text-align: center; color: #e6e9ef;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 7px; }}

QToolButton#Disclosure {{
    background: transparent; border: none; color: #9aa4b2; font-weight: 600;
    padding: 4px;
}}
QToolButton#Disclosure:hover {{ color: #e6e9ef; }}
"""


# --------------------------------------------------------------------------
# Custom toggle switch (prominent, modern)
# --------------------------------------------------------------------------

class ToggleSwitch(QtWidgets.QAbstractButton):
    """A compact animated on/off switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._w, self._h, self._pad = 56, 30, 3
        self.setFixedSize(self._w, self._h)

    def sizeHint(self):
        return QtCore.QSize(self._w, self._h)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QtGui.QColor(OK_GREEN if on else "#3c4453")
        p.setBrush(track)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self._w, self._h, self._h / 2, self._h / 2)
        d = self._h - 2 * self._pad
        x = self._w - d - self._pad if on else self._pad
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawEllipse(int(x), self._pad, d, d)


# --------------------------------------------------------------------------
# Worker thread
# --------------------------------------------------------------------------

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
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.failed.emit(str(exc))


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GoPro Anamorphic Toolkit")
        self.setMinimumSize(720, 680)
        self.setAcceptDrops(True)

        self._settings: Settings = config.load_settings()
        self._files: list[Path] = []
        self._thread: QtCore.QThread | None = None
        self._worker: Worker | None = None

        self._build_ui()
        self.setStyleSheet(STYLESHEET)

    # -- UI construction ---------------------------------------------------

    def _card(self) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout]:
        frame = QtWidgets.QFrame()
        frame.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        return frame, lay

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        # Header
        header = QtWidgets.QWidget()
        header.setObjectName("Header")
        hl = QtWidgets.QVBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(2)
        title = QtWidgets.QLabel("GoPro Anamorphic Toolkit")
        title.setObjectName("Title")
        subtitle = QtWidgets.QLabel(
            "HERO11 · 2.7K 16:9 only · desqueeze 1.2× → ~2.13:1 · full-resolution H.265"
        )
        subtitle.setObjectName("Subtitle")
        hl.addWidget(title)
        hl.addWidget(subtitle)
        outer.addWidget(header)

        # --- Input card ---
        in_card, in_lay = self._card()
        in_lay.addWidget(self._section_label("1 · Input clips"))
        btn_row = QtWidgets.QHBoxLayout()
        self.btn_folder = QtWidgets.QPushButton("Add folder…")
        self.btn_files = QtWidgets.QPushButton("Add files…")
        self.btn_clear = QtWidgets.QPushButton("Clear")
        self.btn_folder.clicked.connect(self._choose_folder)
        self.btn_files.clicked.connect(self._choose_files)
        self.btn_clear.clicked.connect(self._clear_files)
        btn_row.addWidget(self.btn_folder)
        btn_row.addWidget(self.btn_files)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_clear)
        in_lay.addLayout(btn_row)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["File", "Resolution", "FPS", "Gyro", "Status"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            hh.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMinimumHeight(160)
        in_lay.addWidget(self.table)
        self.drop_hint = QtWidgets.QLabel("Drag & drop folders or .MP4 files here")
        self.drop_hint.setObjectName("Subtitle")
        self.drop_hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        in_lay.addWidget(self.drop_hint)
        outer.addWidget(in_card)

        # --- Stabilize toggle card ---
        stab_card, stab_lay = self._card()
        row = QtWidgets.QHBoxLayout()
        txtcol = QtWidgets.QVBoxLayout()
        txtcol.setSpacing(2)
        lbl = QtWidgets.QLabel("Stabilize with Gyroflow")
        lbl.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.stab_desc = QtWidgets.QLabel()
        self.stab_desc.setObjectName("Subtitle")
        txtcol.addWidget(lbl)
        txtcol.addWidget(self.stab_desc)
        row.addLayout(txtcol)
        row.addStretch(1)
        self.toggle = ToggleSwitch()
        self.toggle.setChecked(self._settings.stabilize)
        self.toggle.toggled.connect(self._update_stab_label)
        self.state_lbl = QtWidgets.QLabel()
        self.state_lbl.setStyleSheet("font-weight: 700;")
        self.state_lbl.setFixedWidth(40)
        row.addWidget(self.state_lbl)
        row.addWidget(self.toggle)
        stab_lay.addLayout(row)
        outer.addWidget(stab_card)
        self._update_stab_label(self.toggle.isChecked())

        # --- Output card ---
        out_card, out_lay = self._card()
        out_lay.addWidget(self._section_label("2 · Output folder"))
        orow = QtWidgets.QHBoxLayout()
        self.edit_output = QtWidgets.QLineEdit()
        self.edit_output.setPlaceholderText("Where to save the final videos…")
        btn_out = QtWidgets.QPushButton("Choose…")
        btn_out.clicked.connect(self._choose_output)
        orow.addWidget(self.edit_output)
        orow.addWidget(btn_out)
        out_lay.addLayout(orow)
        outer.addWidget(out_card)

        # --- Advanced (collapsible) ---
        self.adv_toggle = QtWidgets.QToolButton()
        self.adv_toggle.setObjectName("Disclosure")
        self.adv_toggle.setText("  Advanced options")
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setChecked(False)
        self.adv_toggle.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        self.adv_toggle.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.adv_toggle.toggled.connect(self._toggle_advanced)
        outer.addWidget(self.adv_toggle, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)

        self.adv_card, adv_lay = self._card()
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        grow = QtWidgets.QHBoxLayout()
        self.edit_gyroflow = QtWidgets.QLineEdit()
        self.edit_gyroflow.setPlaceholderText("Auto-detected (optional)")
        if self._settings.gyroflow_bin:
            self.edit_gyroflow.setText(self._settings.gyroflow_bin)
        btn_g = QtWidgets.QPushButton("…")
        btn_g.setFixedWidth(34)
        btn_g.clicked.connect(self._choose_gyroflow)
        grow.addWidget(self.edit_gyroflow)
        grow.addWidget(btn_g)
        form.addRow("Gyroflow path:", grow)

        self.spin_crf = QtWidgets.QSpinBox()
        self.spin_crf.setRange(10, 28)
        self.spin_crf.setValue(self._settings.crf)
        self.spin_crf.setToolTip("Lower = higher quality / bigger file. 16–18 is high quality.")
        form.addRow("H.265 CRF:", self.spin_crf)

        self.cmb_preset = QtWidgets.QComboBox()
        self.cmb_preset.addItems(
            ["medium", "slow", "slower", "veryslow"]
        )
        idx = self.cmb_preset.findText(self._settings.preset)
        self.cmb_preset.setCurrentIndex(idx if idx >= 0 else 1)
        form.addRow("x265 preset:", self.cmb_preset)
        adv_lay.addLayout(form)
        self.adv_card.setVisible(False)
        outer.addWidget(self.adv_card)

        # --- Start + progress ---
        self.btn_start = QtWidgets.QPushButton("Start")
        self.btn_start.setObjectName("Primary")
        self.btn_start.clicked.connect(self._start)
        outer.addWidget(self.btn_start)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        outer.addWidget(self.progress)
        self.lbl_status = QtWidgets.QLabel("Ready.")
        self.lbl_status.setObjectName("Subtitle")
        outer.addWidget(self.lbl_status)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setMinimumHeight(140)
        outer.addWidget(self.log, 1)

    def _section_label(self, text: str) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("SectionLabel")
        return lbl

    # -- small handlers ----------------------------------------------------

    def _update_stab_label(self, on: bool) -> None:
        self.state_lbl.setText("ON" if on else "OFF")
        self.state_lbl.setStyleSheet(
            f"font-weight: 700; color: {OK_GREEN if on else '#9aa4b2'};"
        )
        self.stab_desc.setText(
            "Gyroflow + calibrated lens profile, then desqueeze"
            if on
            else "Desqueeze + export only (no stabilization)"
        )

    def _toggle_advanced(self, shown: bool) -> None:
        self.adv_card.setVisible(shown)
        self.adv_toggle.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if shown else QtCore.Qt.ArrowType.RightArrow
        )

    # -- file handling -----------------------------------------------------

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802
        self._add_inputs([Path(u.toLocalFile()) for u in event.mimeData().urls()])

    def _choose_folder(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose input folder")
        if d:
            self._add_inputs([Path(d)])

    def _choose_files(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Choose .MP4 files", filter="GoPro video (*.mp4 *.MP4)"
        )
        if files:
            self._add_inputs([Path(f) for f in files])

    def _clear_files(self) -> None:
        self._files = []
        self.table.setRowCount(0)
        self.lbl_status.setText("Ready.")

    def _add_inputs(self, paths: list[Path]) -> None:
        try:
            found = core.collect_files(paths)
        except core.PipelineError as exc:
            self._warn(str(exc))
            return
        existing = {p.resolve() for p in self._files}
        new = [f for f in found if f.resolve() not in existing]
        if not new:
            self.lbl_status.setText("No new .MP4 files found.")
            return
        self._files.extend(new)
        self._refresh_table(new)
        supported = sum(1 for f in self._files if self._is_supported(f))
        self.lbl_status.setText(
            f"{len(self._files)} file(s) · {supported} ready, "
            f"{len(self._files) - supported} will be skipped."
        )

    def _is_supported(self, path: Path) -> bool:
        try:
            return metadata.probe(path).is_supported
        except metadata.FFprobeError:
            return False

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
                    gyro = "yes" if info.has_gyro else "no"
                    if info.is_supported:
                        status, color = "Ready", OK_GREEN
                    elif not info.is_16by9:
                        status, color = f"Skip · not 16:9 ({info.aspect_label})", BAD
                    else:
                        status, color = "Skip · unsupported resolution", BAD
                    tip = "\n".join(info.warnings)
                    gyro_color = None if info.has_gyro else WARN
                except metadata.FFprobeError as exc:
                    res = fps = gyro = "?"
                    status, color, gyro_color = "Skip · unreadable", BAD, BAD
                    tip = str(exc)
                self._set_cell(row, 0, f.name, tip=tip)
                self._set_cell(row, 1, res)
                self._set_cell(row, 2, fps)
                self._set_cell(row, 3, gyro, color=gyro_color)
                self._set_cell(row, 4, status, color=color)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _set_cell(self, row, col, text, *, color=None, tip=None) -> None:
        item = QtWidgets.QTableWidgetItem(text)
        if color:
            item.setForeground(QtGui.QColor(color))
        if tip:
            item.setToolTip(tip)
        self.table.setItem(row, col, item)

    def _choose_output(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if d:
            self.edit_output.setText(d)

    def _choose_gyroflow(self) -> None:
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose the Gyroflow executable", filter="Gyroflow (*.AppImage gyroflow *)"
        )
        if f:
            self.edit_gyroflow.setText(f)

    # -- run ---------------------------------------------------------------

    def _collect_settings(self) -> Settings:
        return self._settings.merged(
            {
                "stabilize": self.toggle.isChecked(),
                "crf": self.spin_crf.value(),
                "preset": self.cmb_preset.currentText(),
                "gyroflow_bin": self.edit_gyroflow.text().strip() or None,
            }
        )

    def _start(self) -> None:
        if not self._files:
            self._warn("Add at least one .MP4 file.")
            return
        out = self.edit_output.text().strip()
        if not out:
            self._warn("Choose the output folder.")
            return

        settings = self._collect_settings()
        self.log.clear()
        self.progress.setValue(0)
        self._set_running(True)
        self._append_log(
            f"Stabilization: {'ON' if settings.stabilize else 'OFF'} · "
            f"full-res desqueeze {settings.squeeze}x · H.265 CRF {settings.crf} "
            f"preset {settings.preset}"
        )

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
        self.btn_start.setText("Processing…" if running else "Start")
        for w in (self.btn_folder, self.btn_files, self.btn_clear, self.toggle):
            w.setEnabled(not running)

    @QtCore.Slot(str)
    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    @QtCore.Slot(int, int, str, float)
    def _on_progress(self, i: int, n: int, phase: str, frac: float) -> None:
        overall = (i + max(0.0, min(1.0, frac))) / n if n else 0.0
        self.progress.setValue(int(overall * 100))
        self.lbl_status.setText(f"[{i + 1}/{n}] {phase}… {int(frac * 100)}%")

    @QtCore.Slot(object)
    def _on_done(self, report) -> None:
        self._finish_thread()
        self.progress.setValue(100)
        done = report.ok_count
        skipped = sum(1 for r in report.results if r.skipped)
        failed = len(report.failed)
        msg = f"Done: {done} processed · {skipped} skipped · {failed} failed"
        self.lbl_status.setText(msg)
        self._append_log("\n" + msg)
        for r in report.failed:
            self._append_log(f"  FAILED {r.source.name}: {r.message}")
        if failed:
            self._warn(msg + "\nSee the log for details.")
        else:
            QtWidgets.QMessageBox.information(self, "Finished", msg)

    @QtCore.Slot(str)
    def _on_failed(self, message: str) -> None:
        self._finish_thread()
        self.lbl_status.setText("Error.")
        self._append_log(f"ERROR: {message}")
        self._warn(message)

    def _finish_thread(self) -> None:
        self._set_running(False)
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    def _warn(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Notice", message)


def main(argv: list[str] | None = None) -> int:
    app = QtWidgets.QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("GoPro Anamorphic Toolkit")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
