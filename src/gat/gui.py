"""PySide6 GUI of the GoPro Anamorphic Toolkit.

A minimal, modern dark interface that reuses the exact same core as the CLI:
no processing logic is duplicated here. The window has two columns:

* left  — WHAT to process: input clips, output folder, activity log;
* right — HOW to process it: Stabilize toggle, Summer look (with a live
  before/after preview), collapsible Advanced options, and the Start button.

Only GoPro HERO11 2.7K 16:9 clips are processed; anything else is flagged in
the file list and skipped. The whole content sits in a scroll area, so a small
window scrolls instead of squeezing widgets on top of each other.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "PySide6 is not installed. Install the GUI extra with:\n"
        "    pip install -e '.[gui]'\n"
    )
    raise

from . import __version__, config, core, metadata
from .config import Settings

Qt = QtCore.Qt

# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------

BG = "#15171c"
CARD = "#1e2129"
CARD_BORDER = "#2b303b"
FIELD = "#13151a"
TEXT = "#e8ebf1"
TEXT_2 = "#98a2b3"
MUTED = "#6b7280"
ACCENT = "#5b8cff"
ACCENT_HOVER = "#7aa2ff"
ACCENT_PRESSED = "#4a78e6"
GREEN = "#34d399"
WARM = "#fb923c"
AMBER = "#fbbf24"
RED = "#f87171"

_ICON_DIR = config.RESOURCE_DIR / "ui"
_DOWN = (_ICON_DIR / "chevron-down.svg").as_posix()
_UP = (_ICON_DIR / "chevron-up.svg").as_posix()

STYLESHEET = f"""
#Root, #Content, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BG}; }}
QScrollArea {{ border: none; }}
QFrame#Footer {{ background: #191c22; border-top: 1px solid #262a33; }}
QLabel {{ background: transparent; color: {TEXT}; }}
QLabel#Title {{ font-size: 22px; font-weight: 700; }}
QLabel#Subtitle {{ color: {TEXT_2}; font-size: 12px; }}
QLabel#Version {{ color: {MUTED}; font-size: 12px; }}
QLabel#CardTitle {{ font-size: 15px; font-weight: 700; }}
QLabel#Hint {{ color: {TEXT_2}; font-size: 12px; }}
QLabel#Muted {{ color: {MUTED}; font-size: 12px; }}

QFrame#Card {{
    background: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: 14px;
}}

QPushButton {{
    background: #2a2f39;
    border: 1px solid #363c48;
    border-radius: 9px;
    padding: 8px 16px;
    color: {TEXT};
    font-weight: 600;
}}
QPushButton:hover {{ background: #333946; border-color: #414858; }}
QPushButton:pressed {{ background: #262a33; }}
QPushButton:disabled {{ color: {MUTED}; background: #22262e; border-color: #2b303b; }}

QPushButton#Primary {{
    background: {ACCENT};
    border: none;
    color: white;
    font-size: 16px;
    font-weight: 700;
    padding: 14px 22px;
    border-radius: 12px;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#Primary:disabled {{ background: #2f3644; color: #8a93a2; }}

QLineEdit, QSpinBox, QComboBox {{
    background: {FIELD};
    border: 1px solid #343a46;
    border-radius: 9px;
    padding: 7px 10px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox {{ padding-right: 30px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 28px; border: none; background: transparent;
}}
QComboBox::down-arrow {{ image: url("{_DOWN}"); width: 12px; height: 12px; }}
QSpinBox {{ padding-right: 28px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; width: 22px; border: none;
    background: transparent; margin-right: 4px;
}}
QSpinBox::up-button {{ subcontrol-position: top right; margin-top: 4px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 4px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: #2a2f39; border-radius: 4px;
}}
QSpinBox::up-arrow {{ image: url("{_UP}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url("{_DOWN}"); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {CARD}; color: {TEXT}; border: 1px solid {CARD_BORDER};
    selection-background-color: {ACCENT};
}}

QTableWidget {{
    background: {FIELD};
    alternate-background-color: #171a20;
    border: 1px solid #2a2f3a;
    border-radius: 10px;
    gridline-color: transparent;
    color: {TEXT};
}}
QTableWidget[dragActive="true"] {{ border: 2px dashed {ACCENT}; }}
QHeaderView::section {{
    background: {CARD};
    color: {TEXT_2};
    border: none;
    border-bottom: 1px solid #2a2f3a;
    padding: 8px 10px;
    font-weight: 600;
    font-size: 12px;
}}
QTableWidget::item {{ padding: 4px 10px; border: none; }}

QPlainTextEdit {{
    background: {FIELD};
    border: 1px solid #2a2f3a;
    border-radius: 10px;
    padding: 6px;
    font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace;
    font-size: 11px;
    color: #c7cddb;
}}

QProgressBar {{
    background: {FIELD};
    border: 1px solid #2a2f3a;
    border-radius: 7px;
    min-height: 14px;
    max-height: 14px;
    text-align: center;
    color: {TEXT};
    font-size: 11px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}

QSlider::groove:horizontal {{ height: 6px; background: #2a2f39; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {WARM}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: white; width: 18px; height: 18px; margin: -6px 0; border-radius: 9px;
}}
QSlider::handle:horizontal:disabled {{ background: #8a93a2; }}

QToolButton#Disclosure {{
    background: transparent; border: none; color: {TEXT_2};
    font-weight: 600; padding: 4px 2px;
}}
QToolButton#Disclosure:hover {{ color: {TEXT}; }}

QToolTip {{
    background: {CARD}; color: {TEXT}; border: 1px solid {CARD_BORDER};
    padding: 6px; border-radius: 6px;
}}
"""


def apply_theme(app: QtWidgets.QApplication) -> None:
    """Fusion style + dark palette + stylesheet, applied to the whole app.

    The palette also themes the parts the stylesheet does not cover
    (message boxes, menus, scroll bars, combo popups).
    """
    app.setStyle("Fusion")
    pal = QtGui.QPalette()
    roles = QtGui.QPalette.ColorRole
    pal.setColor(roles.Window, QtGui.QColor(BG))
    pal.setColor(roles.WindowText, QtGui.QColor(TEXT))
    pal.setColor(roles.Base, QtGui.QColor(FIELD))
    pal.setColor(roles.AlternateBase, QtGui.QColor("#171a20"))
    pal.setColor(roles.Text, QtGui.QColor(TEXT))
    pal.setColor(roles.Button, QtGui.QColor("#2a2f39"))
    pal.setColor(roles.ButtonText, QtGui.QColor(TEXT))
    pal.setColor(roles.Highlight, QtGui.QColor(ACCENT))
    pal.setColor(roles.HighlightedText, QtGui.QColor("#ffffff"))
    pal.setColor(roles.ToolTipBase, QtGui.QColor(CARD))
    pal.setColor(roles.ToolTipText, QtGui.QColor(TEXT))
    pal.setColor(roles.PlaceholderText, QtGui.QColor(MUTED))
    disabled = QtGui.QPalette.ColorGroup.Disabled
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        pal.setColor(disabled, role, QtGui.QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)


# --------------------------------------------------------------------------
# Small custom widgets
# --------------------------------------------------------------------------

class ToggleSwitch(QtWidgets.QAbstractButton):
    """A large on/off switch whose state is obvious at a glance."""

    def __init__(self, on_color: str = GREEN, parent=None):
        super().__init__(parent)
        self._on_color = on_color
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(54, 30)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(54, 30)

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QtGui.QColor(self._on_color if on else "#3a404d")
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QtCore.QRectF(0, 0, 54, 30), 15, 15)
        if self.hasFocus():
            p.setPen(QtGui.QPen(QtGui.QColor(ACCENT_HOVER), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QtCore.QRectF(1, 1, 52, 28), 14, 14)
            p.setPen(Qt.PenStyle.NoPen)
        knob = 24
        x = 54 - knob - 3 if on else 3
        p.setBrush(QtGui.QColor("#ffffff" if self.isEnabled() else "#c5cad3"))
        p.drawEllipse(QtCore.QRectF(x, 3, knob, knob))


class FileTable(QtWidgets.QTableWidget):
    """File list that shows a friendly placeholder while empty."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.rowCount():
            return
        p = QtGui.QPainter(self.viewport())
        rect = self.viewport().rect()
        p.setPen(QtGui.QColor(TEXT_2))
        f = p.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setBold(True)
        p.setFont(f)
        p.drawText(rect.adjusted(0, -14, 0, -14), Qt.AlignmentFlag.AlignCenter,
                   "Drop GoPro .MP4 files or a folder here")
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() - 2)
        p.setFont(f)
        p.setPen(QtGui.QColor(MUTED))
        p.drawText(rect.adjusted(0, 16, 0, 16), Qt.AlignmentFlag.AlignCenter,
                   "or use “Add folder…” / “Add files…” above")


class CompareView(QtWidgets.QWidget):
    """Before/after image comparison with a draggable divider."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._before: QtGui.QPixmap | None = None
        self._after: QtGui.QPixmap | None = None
        self._split = 0.5
        self._aspect = 600 / 1280
        self._message = "Rendering preview…"
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(240)
        self.setFixedHeight(180)
        self.setToolTip("Drag to compare the original (left) with the Summer look (right)")

    def set_before(self, pix: QtGui.QPixmap | None) -> None:
        self._before = pix
        if pix is not None and pix.width():
            self._aspect = pix.height() / pix.width()
            self._fit_height()
        self.update()

    def set_after(self, pix: QtGui.QPixmap | None) -> None:
        self._after = pix
        self.update()

    def set_message(self, text: str) -> None:
        self._message = text
        self.update()

    def _fit_height(self) -> None:
        h = max(120, int(self.width() * self._aspect))
        if h != self.height():
            self.setFixedHeight(h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_height()

    def _set_split_from(self, x: float) -> None:
        if self.width():
            self._split = max(0.02, min(0.98, x / self.width()))
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_split_from(event.position().x())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_split_from(event.position().x())

    def _pill(self, p: QtGui.QPainter, text: str, right: bool) -> None:
        f = p.font()
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        fm = QtGui.QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 16, fm.height() + 6
        x = self.width() - w - 10 if right else 10
        rect = QtCore.QRectF(x, 10, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 150))
        p.drawRoundedRect(rect, h / 2, h / 2)
        p.setPen(QtGui.QColor("#ffffff"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        r = QtCore.QRectF(self.rect())
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(r, 10, 10)
        p.setClipPath(clip)
        p.fillRect(r, QtGui.QColor("#0f1115"))
        if self._before is None or self._after is None:
            p.setPen(QtGui.QColor(TEXT_2))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._message)
            return
        x = r.width() * self._split
        for pix, part in ((self._before, QtCore.QRectF(0, 0, x, r.height())),
                          (self._after, QtCore.QRectF(x, 0, r.width() - x, r.height()))):
            p.save()
            p.setClipRect(part, Qt.ClipOperation.IntersectClip)
            p.drawPixmap(r, pix, QtCore.QRectF(pix.rect()))
            p.restore()
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 235), 2))
        p.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, r.height()))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor("#ffffff"))
        center = QtCore.QPointF(x, r.height() / 2)
        p.drawEllipse(center, 12, 12)
        p.setPen(QtGui.QPen(QtGui.QColor(BG), 2))
        for sign in (-1, 1):  # two small chevrons on the handle
            cx = center.x() + sign * 4
            p.drawLine(QtCore.QPointF(cx, center.y() - 4), QtCore.QPointF(cx + sign * 3, center.y()))
            p.drawLine(QtCore.QPointF(cx + sign * 3, center.y()), QtCore.QPointF(cx, center.y() + 4))
        self._pill(p, "BEFORE", right=False)
        self._pill(p, "AFTER", right=True)


# --------------------------------------------------------------------------
# Background work
# --------------------------------------------------------------------------

class Worker(QtCore.QObject):
    """Runs the shared core pipeline in a QThread."""

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


class _TaskSignals(QtCore.QObject):
    ready = QtCore.Signal(str, int, object)  # kind, request id, payload
    failed = QtCore.Signal(str, int, str)


class _Task(QtCore.QRunnable):
    """Runs one preview job (frame extraction or look rendering) off the UI thread."""

    def __init__(self, kind: str, rid: int, fn, signals: _TaskSignals):
        super().__init__()
        self.kind, self.rid, self.fn, self.signals = kind, rid, fn, signals

    def run(self) -> None:
        try:
            self.signals.ready.emit(self.kind, self.rid, self.fn())
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self.kind, self.rid, str(exc))


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GoPro Anamorphic Toolkit")
        self.setAcceptDrops(True)
        self.setMinimumSize(900, 600)

        self._settings: Settings = config.load_settings()
        self._files: list[Path] = []
        self._infos: dict[Path, metadata.MediaInfo | None] = {}
        self._thread: QtCore.QThread | None = None
        self._worker: Worker | None = None

        # Preview state
        self._tmpdir = Path(tempfile.mkdtemp(prefix="gat-preview-"))
        self._frame_cache: dict[Path, Path] = {}
        self._preview_base: Path | None = None
        self._latest: dict[str, int] = {"base": 0, "before": 0, "after": 0}
        self._rid = 0
        self._pool = QtCore.QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._signals = _TaskSignals()
        self._signals.ready.connect(self._on_task_ready)
        self._signals.failed.connect(self._on_task_failed)
        self._after_timer = QtCore.QTimer(self)
        self._after_timer.setSingleShot(True)
        self._after_timer.setInterval(120)
        self._after_timer.timeout.connect(self._render_after)

        self._build_ui()
        self._resize_to_screen()

    # -- construction -------------------------------------------------------

    def _resize_to_screen(self) -> None:
        screen = QtGui.QGuiApplication.primaryScreen()
        w, h = 1160, 880
        if screen is not None:
            avail = screen.availableGeometry()
            w = min(w, int(avail.width() * 0.95))
            h = min(h, int(avail.height() * 0.92))
        self.resize(w, h)

    @staticmethod
    def _card() -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout]:
        frame = QtWidgets.QFrame()
        frame.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(frame)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        return frame, lay

    @staticmethod
    def _label(text: str, name: str | None = None, wrap: bool = False) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        if name:
            lbl.setObjectName(name)
        lbl.setWordWrap(wrap)
        return lbl

    def _toggle_card(self, title: str, color: str) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout,
                                                             ToggleSwitch, QtWidgets.QLabel,
                                                             QtWidgets.QLabel]:
        card, lay = self._card()
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        texts = QtWidgets.QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(self._label(title, "CardTitle"))
        desc = self._label("", "Hint", wrap=True)
        texts.addWidget(desc)
        row.addLayout(texts, 1)
        state = QtWidgets.QLabel()
        state.setMinimumWidth(34)
        state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(state)
        switch = ToggleSwitch(color)
        row.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(row)
        return card, lay, switch, desc, state

    def _build_ui(self) -> None:
        # Root = scrollable content on top + fixed action bar at the bottom, so
        # the Start button is always visible whatever is expanded.
        root = QtWidgets.QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        root_lay = QtWidgets.QVBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        root_lay.addWidget(scroll, 1)
        content = QtWidgets.QWidget()
        content.setObjectName("Content")
        scroll.setWidget(content)
        outer = QtWidgets.QVBoxLayout(content)
        outer.setContentsMargins(26, 22, 26, 18)
        outer.setSpacing(18)

        # Header
        header = QtWidgets.QHBoxLayout()
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self._label("GoPro Anamorphic Toolkit", "Title"))
        titles.addWidget(self._label(
            "HERO11 · 2.7K 16:9 · Neewer LS-56 1.2× desqueeze → ~2.13:1 · full-resolution H.265",
            "Subtitle"))
        header.addLayout(titles, 1)
        header.addWidget(self._label(f"v{__version__}", "Version"), 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        columns = QtWidgets.QHBoxLayout()
        columns.setSpacing(18)
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(18)
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(18)
        columns.addLayout(left, 11)
        columns.addLayout(right, 9)
        outer.addLayout(columns, 1)

        # ---- Left: input clips --------------------------------------------
        in_card, in_lay = self._card()
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self._label("Input clips", "CardTitle"))
        head.addStretch(1)
        self.btn_folder = QtWidgets.QPushButton("Add folder…")
        self.btn_folder.setToolTip("Add every .MP4 file of a folder")
        self.btn_files = QtWidgets.QPushButton("Add files…")
        self.btn_files.setToolTip("Pick one or more .MP4 files")
        self.btn_clear = QtWidgets.QPushButton("Clear list")
        self.btn_clear.setToolTip("Remove all clips from the list")
        self.btn_folder.clicked.connect(self._choose_folder)
        self.btn_files.clicked.connect(self._choose_files)
        self.btn_clear.clicked.connect(self._clear_files)
        for b in (self.btn_folder, self.btn_files, self.btn_clear):
            head.addWidget(b)
        in_lay.addLayout(head)

        self.table = FileTable(0, 5)
        self.table.setHorizontalHeaderLabels(["File", "Resolution", "FPS", "Gyro", "Status"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            hh.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setHighlightSections(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setMinimumHeight(150)
        # Fill the available space but never demand more than the minimum.
        self.table.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                 QtWidgets.QSizePolicy.Policy.Ignored)
        in_lay.addWidget(self.table, 1)
        self.lbl_files = self._label("Only 2.7K 16:9 clips are processed — other formats are skipped.",
                                     "Muted", wrap=True)
        in_lay.addWidget(self.lbl_files)
        left.addWidget(in_card, 3)

        # ---- Left: output folder -------------------------------------------
        out_card, out_lay = self._card()
        out_lay.addWidget(self._label("Output folder", "CardTitle"))
        orow = QtWidgets.QHBoxLayout()
        orow.setSpacing(8)
        self.edit_output = QtWidgets.QLineEdit()
        self.edit_output.setPlaceholderText("Choose where the final videos are saved")
        btn_out = QtWidgets.QPushButton("Browse…")
        btn_out.clicked.connect(self._choose_output)
        orow.addWidget(self.edit_output, 1)
        orow.addWidget(btn_out)
        out_lay.addLayout(orow)
        left.addWidget(out_card)

        # ---- Left: log -----------------------------------------------------
        log_card, log_lay = self._card()
        log_lay.addWidget(self._label("Activity log", "CardTitle"))
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setMinimumHeight(100)
        self.log.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                               QtWidgets.QSizePolicy.Policy.Ignored)
        self.log.setPlaceholderText("Processing details will appear here.")
        log_lay.addWidget(self.log, 1)
        left.addWidget(log_card, 2)

        # ---- Right: stabilize ----------------------------------------------
        stab_card, _, self.toggle, self.stab_desc, self.stab_state = self._toggle_card(
            "Stabilize with Gyroflow", GREEN)
        self.toggle.setChecked(self._settings.stabilize)
        self.toggle.toggled.connect(self._update_stab_label)
        right.addWidget(stab_card)
        self._update_stab_label(self.toggle.isChecked())

        # ---- Right: summer look --------------------------------------------
        look_card, look_lay, self.look_toggle, self.look_desc, self.look_state = self._toggle_card(
            "Summer look", WARM)
        self.look_toggle.setChecked(self._settings.look)
        self.look_toggle.toggled.connect(self._on_look_toggled)

        self.look_body = QtWidgets.QWidget()
        body = QtWidgets.QVBoxLayout(self.look_body)
        body.setContentsMargins(0, 4, 0, 0)
        body.setSpacing(10)
        irow = QtWidgets.QHBoxLayout()
        irow.setSpacing(12)
        irow.addWidget(self._label("Intensity", "Hint"))
        self.slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(self._settings.look_intensity)
        self.slider.setToolTip("Even at 100% the look stays subtle")
        self.slider.valueChanged.connect(self._on_intensity_changed)
        irow.addWidget(self.slider, 1)
        self.lbl_intensity = QtWidgets.QLabel()
        self.lbl_intensity.setMinimumWidth(40)
        self.lbl_intensity.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        irow.addWidget(self.lbl_intensity)
        body.addLayout(irow)

        prow = QtWidgets.QHBoxLayout()
        prow.setSpacing(12)
        prow.addWidget(self._label("Preview", "Hint"))
        self.cmb_preview = QtWidgets.QComboBox()
        self.cmb_preview.setToolTip("Sample images or a frame of your own clips")
        for label, path in config.preview_samples().items():
            self.cmb_preview.addItem(label, ("sample", str(path)))
        self.cmb_preview.currentIndexChanged.connect(self._on_preview_source_changed)
        prow.addWidget(self.cmb_preview, 1)
        body.addLayout(prow)
        self.compare = CompareView()
        body.addWidget(self.compare)
        body.addWidget(self._label("Drag the divider to compare. The export uses exactly this filter.",
                                   "Muted", wrap=True))
        look_lay.addWidget(self.look_body)
        right.addWidget(look_card)
        self._update_intensity_label(self.slider.value())
        self._on_look_toggled(self.look_toggle.isChecked())

        # ---- Right: advanced (collapsible) ---------------------------------
        self.adv_toggle = QtWidgets.QToolButton()
        self.adv_toggle.setObjectName("Disclosure")
        self.adv_toggle.setText("Advanced options")
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.adv_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.adv_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.adv_toggle.toggled.connect(self._toggle_advanced)
        right.addWidget(self.adv_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.adv_card, adv_lay = self._card()
        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grow = QtWidgets.QHBoxLayout()
        grow.setSpacing(8)
        self.edit_gyroflow = QtWidgets.QLineEdit()
        self.edit_gyroflow.setPlaceholderText("Auto-detected")
        if self._settings.gyroflow_bin:
            self.edit_gyroflow.setText(self._settings.gyroflow_bin)
        btn_g = QtWidgets.QPushButton("Browse…")
        btn_g.clicked.connect(self._choose_gyroflow)
        grow.addWidget(self.edit_gyroflow, 1)
        grow.addWidget(btn_g)
        form.addRow(self._label("Gyroflow app", "Hint"), grow)
        self.spin_crf = QtWidgets.QSpinBox()
        self.spin_crf.setRange(10, 28)
        self.spin_crf.setValue(self._settings.crf)
        self.spin_crf.setToolTip("Lower = higher quality and bigger files. 16–18 is high quality.")
        form.addRow(self._label("H.265 CRF", "Hint"), self.spin_crf)
        self.cmb_preset = QtWidgets.QComboBox()
        self.cmb_preset.addItems(["medium", "slow", "slower", "veryslow"])
        idx = self.cmb_preset.findText(self._settings.preset)
        self.cmb_preset.setCurrentIndex(idx if idx >= 0 else 1)
        self.cmb_preset.setToolTip("Slower presets compress better at the same quality")
        form.addRow(self._label("x265 preset", "Hint"), self.cmb_preset)
        adv_lay.addLayout(form)
        self.adv_card.setVisible(False)
        right.addWidget(self.adv_card)

        right.addStretch(1)

        # ---- Footer: always-visible action bar -----------------------------
        footer = QtWidgets.QFrame()
        footer.setObjectName("Footer")
        flay = QtWidgets.QHBoxLayout(footer)
        flay.setContentsMargins(26, 14, 26, 16)
        flay.setSpacing(22)
        status_col = QtWidgets.QVBoxLayout()
        status_col.setSpacing(8)
        self.lbl_status = self._label("Ready.", "Hint")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        status_col.addStretch(1)
        status_col.addWidget(self.lbl_status)
        status_col.addWidget(self.progress)
        status_col.addStretch(1)
        flay.addLayout(status_col, 1)
        self.btn_start = QtWidgets.QPushButton("Start")
        self.btn_start.setObjectName("Primary")
        self.btn_start.setMinimumWidth(240)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.clicked.connect(self._start)
        flay.addWidget(self.btn_start)
        root_lay.addWidget(footer)

        self._refresh_file_summary()

    # -- toggles & labels ----------------------------------------------------

    @staticmethod
    def _set_state(label: QtWidgets.QLabel, on: bool, color: str) -> None:
        label.setText("ON" if on else "OFF")
        label.setStyleSheet(f"font-weight: 700; color: {color if on else MUTED};")

    def _update_stab_label(self, on: bool) -> None:
        self._set_state(self.stab_state, on, GREEN)
        self.stab_desc.setText(
            "Gyroflow + calibrated lens profile, then desqueeze."
            if on else "Off — desqueeze + export only."
        )

    def _on_look_toggled(self, on: bool) -> None:
        self._set_state(self.look_state, on, WARM)
        self.look_desc.setText("A touch more saturation and warmth — a happier, summery tone.")
        self.look_body.setVisible(on)
        if on and self.compare._before is None:
            self._on_preview_source_changed()

    def _update_intensity_label(self, value: int) -> None:
        self.lbl_intensity.setText(f"{value}%")

    def _on_intensity_changed(self, value: int) -> None:
        self._update_intensity_label(value)
        self._after_timer.start()

    def _toggle_advanced(self, shown: bool) -> None:
        self.adv_card.setVisible(shown)
        self.adv_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

    # -- preview -------------------------------------------------------------

    def _submit(self, kind: str, fn) -> None:
        self._rid += 1
        self._latest[kind] = self._rid
        self._pool.start(_Task(kind, self._rid, fn, self._signals))

    def _on_preview_source_changed(self, *_args) -> None:
        if not self.look_toggle.isChecked():
            return
        data = self.cmb_preview.currentData()
        if not data:
            return
        kind, value = data
        self.compare.set_before(None)
        self.compare.set_after(None)
        self.compare.set_message("Rendering preview…")
        self._preview_base = None
        if kind == "sample":
            self._use_preview_base(Path(value))
        else:
            clip = Path(value)
            cached = self._frame_cache.get(clip)
            if cached and cached.exists():
                self._use_preview_base(cached)
            else:
                dest = self._tmpdir / f"frame_{len(self._frame_cache)}_{clip.stem}.png"
                self._submit("base", lambda: (clip, core.extract_preview_frame(clip, dest)))

    def _use_preview_base(self, image: Path) -> None:
        self._preview_base = image
        self._submit("before", lambda: core.render_look_preview(image, 0))
        self._render_after()

    def _render_after(self) -> None:
        if self._preview_base is None or not self.look_toggle.isChecked():
            return
        image, k = self._preview_base, self.slider.value()
        self._submit("after", lambda: core.render_look_preview(image, k))

    @QtCore.Slot(str, int, object)
    def _on_task_ready(self, kind: str, rid: int, payload) -> None:
        if rid != self._latest.get(kind):
            return  # a newer request superseded this one
        if kind == "base":
            clip, frame = payload
            self._frame_cache[clip] = frame
            self._use_preview_base(frame)
            return
        pix = QtGui.QPixmap()
        pix.loadFromData(payload, "PNG")
        if kind == "before":
            self.compare.set_before(pix)
        else:
            self.compare.set_after(pix)

    @QtCore.Slot(str, int, str)
    def _on_task_failed(self, kind: str, rid: int, message: str) -> None:
        if rid == self._latest.get(kind):
            self.compare.set_message("Preview unavailable")
            self.compare.setToolTip(message)

    def _sync_preview_sources(self) -> None:
        """Offer a frame of each supported clip (first 6) as preview source."""
        current = self.cmb_preview.currentData()
        self.cmb_preview.blockSignals(True)
        for i in range(self.cmb_preview.count() - 1, -1, -1):
            if self.cmb_preview.itemData(i)[0] == "clip":
                self.cmb_preview.removeItem(i)
        clips = [f for f in self._files if (self._infos.get(f) and self._infos[f].is_supported)][:6]
        for f in clips:
            self.cmb_preview.addItem(f"Your clip · {f.name}", ("clip", str(f)))
        idx = next((i for i in range(self.cmb_preview.count())
                    if tuple(self.cmb_preview.itemData(i)) == tuple(current or ())), -1)
        self.cmb_preview.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_preview.blockSignals(False)
        if idx < 0:
            self._on_preview_source_changed()

    # -- file handling -------------------------------------------------------

    def _set_drag_active(self, active: bool) -> None:
        self.table.setProperty("dragActive", active)
        self.table.style().unpolish(self.table)
        self.table.style().polish(self.table)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and self._thread is None:
            event.acceptProposedAction()
            self._set_drag_active(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802
        self._set_drag_active(False)
        self._add_inputs([Path(u.toLocalFile()) for u in event.mimeData().urls()])

    def _choose_folder(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose a folder of GoPro clips")
        if d:
            self._add_inputs([Path(d)])

    def _choose_files(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Choose GoPro .MP4 files", filter="GoPro video (*.mp4 *.MP4)"
        )
        if files:
            self._add_inputs([Path(f) for f in files])

    def _clear_files(self) -> None:
        self._files = []
        self._infos = {}
        self.table.setRowCount(0)
        self._refresh_file_summary()
        self._sync_preview_sources()

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
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for f in new:
                try:
                    self._infos[f] = metadata.probe(f)
                except metadata.FFprobeError:
                    self._infos[f] = None
                self._files.append(f)
                self._add_row(f, self._infos[f])
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._refresh_file_summary()
        self._sync_preview_sources()

    def _add_row(self, f: Path, info: metadata.MediaInfo | None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        # Short status text; the full reason is in the tooltip.
        if info is None:
            cells = [(f.name, None), ("?", None), ("?", None), ("?", None),
                     ("● Skip (unreadable)", RED)]
            tip = "ffprobe could not read this file."
        else:
            if info.is_supported:
                status = ("● Ready", GREEN)
            elif not info.is_16by9:
                status = (f"● Skip ({info.aspect_label})", RED)
            else:
                status = ("● Skip (resolution)", RED)
            gyro = ("Yes", None) if info.has_gyro else ("No", AMBER)
            cells = [(f.name, None), (f"{info.width}×{info.height}", None),
                     (f"{info.fps:.2f}", None), gyro, status]
            tip = "\n".join(info.warnings)
        for col, (text, color) in enumerate(cells):
            item = QtWidgets.QTableWidgetItem(text)
            if color:
                item.setForeground(QtGui.QColor(color))
            if tip:
                item.setToolTip(tip)
            self.table.setItem(row, col, item)

    def _supported_files(self) -> list[Path]:
        return [f for f in self._files if self._infos.get(f) and self._infos[f].is_supported]

    def _refresh_file_summary(self) -> None:
        n = len(self._files)
        self.btn_clear.setEnabled(n > 0)
        if not n:
            self.lbl_files.setText("Only 2.7K 16:9 clips are processed — other formats are skipped.")
            return
        ready = len(self._supported_files())
        skipped = n - ready
        text = f"{n} clip{'s' if n != 1 else ''} · {ready} ready"
        if skipped:
            text += f" · {skipped} will be skipped (not 2.7K 16:9)"
        self.lbl_files.setText(text)

    def _choose_output(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose the output folder")
        if d:
            self.edit_output.setText(d)

    def _choose_gyroflow(self) -> None:
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose the Gyroflow executable or AppImage")
        if f:
            self.edit_gyroflow.setText(f)

    # -- run -----------------------------------------------------------------

    def _collect_settings(self) -> Settings:
        return self._settings.merged(
            {
                "stabilize": self.toggle.isChecked(),
                "look": self.look_toggle.isChecked(),
                "look_intensity": self.slider.value(),
                "crf": self.spin_crf.value(),
                "preset": self.cmb_preset.currentText(),
                "gyroflow_bin": self.edit_gyroflow.text().strip() or None,
            }
        )

    def _start(self) -> None:
        if not self._files:
            self._warn("Add at least one GoPro .MP4 clip first.")
            return
        if not self._supported_files():
            self._warn("None of the clips is 2.7K 16:9, so there is nothing to process.")
            return
        out = self.edit_output.text().strip()
        if not out:
            self._warn("Choose an output folder first.")
            return

        settings = self._collect_settings()
        look_k = core.effective_look_intensity(settings)
        self.log.clear()
        self.progress.setValue(0)
        self._set_running(True)
        self._append_log(
            f"Stabilization: {'ON' if settings.stabilize else 'OFF'} · "
            f"Summer look: {str(look_k) + '%' if look_k else 'OFF'} · "
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
        for w in (self.btn_folder, self.btn_files, self.toggle, self.look_toggle,
                  self.slider, self.adv_card):
            w.setEnabled(not running)
        self.btn_clear.setEnabled(not running and bool(self._files))

    @QtCore.Slot(str)
    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    @QtCore.Slot(int, int, str, float)
    def _on_progress(self, i: int, n: int, phase: str, frac: float) -> None:
        overall = (i + max(0.0, min(1.0, frac))) / n if n else 0.0
        self.progress.setValue(int(overall * 100))
        self.lbl_status.setText(f"Clip {i + 1} of {n} · {phase} {int(frac * 100)}%")

    @QtCore.Slot(object)
    def _on_done(self, report) -> None:
        self._finish_thread()
        self.progress.setValue(100)
        failed = len(report.failed)
        msg = (f"Done: {report.ok_count} processed · {report.skipped_count} skipped · "
               f"{failed} failed")
        self.lbl_status.setText(msg)
        self._append_log("\n" + msg)
        for r in report.failed:
            self._append_log(f"  FAILED {r.source.name}: {r.message}")
        if failed:
            self._warn(msg + "\nSee the activity log for details.")
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
        QtWidgets.QMessageBox.warning(self, "GoPro Anamorphic Toolkit", message)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._pool.waitForDone(2000)
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    app = QtWidgets.QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("GoPro Anamorphic Toolkit")
    apply_theme(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
