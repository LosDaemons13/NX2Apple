"""The build log as the window shows it, and a larger window of it.

LogView follows the end of the log only while it is at the end: the progress line of a stage changes each second, and
a log that went back to the end on each of them could not be read higher up. Errors are red and warnings amber
(log_lines.kind). LogWindow is the same log in a window of its own, resizable, for a build of thousands of lines.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from . import log_lines, style

_BEAT_STAGE = re.compile(r'^(?:\[\d\d:\d\d:\d\d\]\s*)?(\[\d+/\d+\])')


class LogView(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.document().setUndoRedoEnabled(False)   # a build's log is never undone, and its undo steps would only take memory
        self._beat_mark: tuple[str, int] | None = None   # (stage, characters in the log right after that beat)
        self._plain = QTextCharFormat()
        self._formats = {log_lines.PLAIN: self._plain}
        for k, color in ((log_lines.ERROR, style.RED), (log_lines.WARNING, style.AMBER)):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            self._formats[k] = f

    # ---------------------------------------------------------------- the end of the log

    def at_end(self) -> bool:
        sb = self.verticalScrollBar()
        return sb.value() >= sb.maximum()

    def _keeping_place(self, edit: Callable[[], None]) -> None:
        """Run an edit at the end of the log: the view stays where the reader is, and follows only from the end."""
        sb = self.verticalScrollBar()
        follow, place = self.at_end(), sb.value()
        edit()
        sb.setValue(sb.maximum() if follow else place)

    def _insert(self, c: QTextCursor, s: str) -> None:
        """Insert `s` at `c` (in place of its selection) and colour each line it touches by its kind (a line it ends is
        read whole)."""
        doc = self.document()
        first = doc.findBlock(c.selectionStart()).blockNumber()
        c.insertText(s, self._plain)
        b, last = doc.findBlockByNumber(first), c.block()
        while b.isValid():
            k = log_lines.kind(b.text())
            if k:
                sel = QTextCursor(b)
                sel.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                sel.setCharFormat(self._formats[k])
            if b == last:
                break
            b = b.next()

    def append_text(self, s: str) -> None:
        """Add text at the end of the log (it may hold several lines)."""
        def edit() -> None:
            c = QTextCursor(self.document())
            c.movePosition(QTextCursor.MoveOperation.End)
            self._insert(c, s)
        self._keeping_place(edit)

    def replace_beat(self, s: str) -> None:
        """A progress line, each second: it takes the place of the stage's previous one when nothing came in between."""
        doc = self.document()
        stage = _BEAT_STAGE.match(s)
        stage_key = stage.group(1) if stage else ''
        last = self._beat_mark

        def edit() -> None:
            c = QTextCursor(doc)
            c.movePosition(QTextCursor.MoveOperation.End)
            if last is not None and last[0] == stage_key and last[1] == doc.characterCount():
                c.movePosition(QTextCursor.MoveOperation.PreviousBlock)
                c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                c.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            self._insert(c, s)
        self._keeping_place(edit)
        self._beat_mark = (stage_key, doc.characterCount())

    def clear(self) -> None:
        super().clear()
        self.document().setUndoRedoEnabled(False)
        self._beat_mark = None

    def copy_from(self, other: 'LogView') -> None:
        """Show what `other` shows (the larger window opens with the log so far), at its end."""
        self.clear()
        self.append_text(other.toPlainText())
        mark = other._beat_mark
        if mark is not None and mark[1] == other.document().characterCount():
            self._beat_mark = (mark[0], self.document().characterCount())
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    # ---------------------------------------------------------------- finding a passage

    def last_error_block(self, before: int | None = None) -> int | None:
        """The number of the last error line (before block `before`), None when there is none."""
        b = self.document().lastBlock() if before is None else self.document().findBlockByNumber(before).previous()
        while b.isValid():
            if log_lines.kind(b.text()) == log_lines.ERROR:
                return b.blockNumber()
            b = b.previous()
        return None

    def first_error_block(self, start: int) -> int | None:
        """The number of the first error line at or after block `start`, None when there is none."""
        b = self.document().findBlockByNumber(max(start, 0))
        while b.isValid():
            if log_lines.kind(b.text()) == log_lines.ERROR:
                return b.blockNumber()
            b = b.next()
        return None

    def show_block(self, number: int) -> None:
        """Select line `number` and scroll it to the middle of the view."""
        b = self.document().findBlockByNumber(number)
        if not b.isValid():
            return
        c = QTextCursor(b)
        c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(c)
        self.centerCursor()


class LogWindow(QDialog):
    """The build log in a window of its own: resizable, and it can stay open beside the launcher."""

    def __init__(self, t: Callable[..., str], source: LogView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.t = t
        self.source = source
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinimizeButtonHint)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(style.STYLESHEET)
        self.setMinimumSize(520, 320)
        self.resize(1100, 720)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(10)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName('rowTitle')
        head.addWidget(self.title)
        head.addStretch(1)
        self.error_btn = QPushButton()
        self.error_btn.setObjectName('ghost')
        self.error_btn.clicked.connect(self.previous_error)
        head.addWidget(self.error_btn)
        self.end_btn = QPushButton()
        self.end_btn.setObjectName('ghost')
        self.end_btn.clicked.connect(self.go_to_end)
        head.addWidget(self.end_btn)
        lay.addLayout(head)
        self.view = LogView()
        lay.addWidget(self.view, 1)
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(self.t('build.log'))
        self.title.setText(self.t('build.log'))
        self.error_btn.setText(self.t('log.previousError'))
        self.error_btn.setToolTip(self.t('log.previousErrorHelp'))
        self.end_btn.setText(self.t('log.toEnd'))

    def show_log(self, block: int | None = None) -> None:
        """Show the window with the log so far, at its end or at line `block` (once the window has its size)."""
        if not self.isVisible():
            self.view.copy_from(self.source)
        self.show()
        self.raise_()
        self.activateWindow()
        if block is not None:
            QTimer.singleShot(0, lambda: self.view.show_block(block))

    def previous_error(self) -> None:
        """The error line before the one selected (the last one at first), so each click goes one further back."""
        c = self.view.textCursor()
        at = self.view.last_error_block(c.blockNumber() if c.hasSelection() else None)
        if at is None:
            at = self.view.last_error_block()   # past the first: around again from the end
        if at is not None:
            self.view.show_block(at)

    def go_to_end(self) -> None:
        c = self.view.textCursor()
        c.clearSelection()
        self.view.setTextCursor(c)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
