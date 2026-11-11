"""The build queue dialog: tick the games to build one after the other (build_queue.py)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from . import style
from .build_queue import QueueRow
from .widgets import CardGroup, LauncherSwitch

if TYPE_CHECKING:
    from .model import Model


class BuildQueueDialog(QDialog):
    def __init__(self, model: 'Model', rows: list[QueueRow], *, adding: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.m = model
        self.rows = rows
        self.adding = adding
        self.chosen: list[str] = [r.title_id for r in rows if r.checked and r.enabled]
        self._switches: dict[str, LauncherSwitch] = {}
        t = self.m.t
        self.setWindowTitle(t('queue.title'))
        self.setMinimumSize(600, 480)
        self.setStyleSheet(style.STYLESHEET)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(14)
        title = QLabel(t('queue.title'))
        title.setStyleSheet('font-size: 20px; font-weight: 800;')
        lay.addWidget(title)
        note = QLabel(t('queue.note'))
        note.setObjectName('muted')
        note.setWordWrap(True)
        lay.addWidget(note)

        group = CardGroup()
        for idx, row in enumerate(rows):
            if idx:
                group.add_divider()
            w = QWidget()
            rl = QHBoxLayout(w)
            rl.setContentsMargins(18, 10, 18, 10)
            rl.setSpacing(12)
            sw = LauncherSwitch(checked=row.checked and row.enabled)
            sw.setEnabled(row.enabled)
            sw.toggled.connect(lambda on, tid=row.title_id: self._toggle(tid, on))
            self._switches[row.title_id] = sw
            rl.addWidget(sw)
            col = QVBoxLayout()
            col.setSpacing(2)
            name = QLabel(row.name)
            name.setObjectName('rowTitle')
            status = QLabel(self._status_text(row))
            status.setObjectName('muted')
            status.setWordWrap(True)
            if row.status == 'version':
                status.setStyleSheet(f'color: {style.AMBER};')
            col.addWidget(name)
            col.addWidget(status)
            rl.addLayout(col, 1)
            group.add_row(w)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(group)
        lay.addWidget(scroll, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton(t('queue.cancel'))
        cancel.setObjectName('ghost')
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        self.start_btn = QPushButton('')
        self.start_btn.setObjectName('creamPill')
        self.start_btn.clicked.connect(self.accept)
        foot.addWidget(self.start_btn)
        lay.addLayout(foot)
        self._update()

    def _status_text(self, row: QueueRow) -> str:
        t = self.m.t
        if row.status == 'version':
            return t('queue.statusVersion', row.supported)
        return t('queue.status.' + row.status)

    def _toggle(self, title_id: str, on: bool) -> None:
        if on and title_id not in self.chosen:
            self.chosen.append(title_id)
        elif not on and title_id in self.chosen:
            self.chosen.remove(title_id)
        self._update()

    def _update(self) -> None:
        # the library's order, whatever order the switches were flipped in
        order = [r.title_id for r in self.rows]
        self.chosen.sort(key=order.index)
        n = len(self.chosen)
        self.start_btn.setText(self.m.t('queue.add' if self.adding else 'queue.start', n))
        self.start_btn.setEnabled(n > 0)
