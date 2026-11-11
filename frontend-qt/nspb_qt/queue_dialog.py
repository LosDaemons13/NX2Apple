"""The build queue dialog: tick the games to build one after the other and put them in order (build_queue.py)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from . import style
from .build_estimate import format_duration
from .build_queue import QueueRow
from .widgets import CardGroup, LauncherSwitch

if TYPE_CHECKING:
    from .model import Model


def initial_order(rows: list[QueueRow], waiting: list[str] = ()) -> list[QueueRow]:
    """Games already waiting first, in the queue's order; then the others in the library's order; last, the rows that
    cannot be ticked (the game being built, games whose files are gone)."""
    rank = {tid.upper(): i for i, tid in enumerate(waiting)}
    queued = sorted((r for r in rows if r.title_id.upper() in rank), key=lambda r: rank[r.title_id.upper()])
    rest = [r for r in rows if r.title_id.upper() not in rank and r.enabled]
    fixed = [r for r in rows if r.title_id.upper() not in rank and not r.enabled]
    return queued + rest + fixed


class BuildQueueDialog(QDialog):
    def __init__(self, model: 'Model', rows: list[QueueRow], *, adding: bool, waiting: list[str] = (),
                 estimates: dict[str, int | None] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.m = model
        self.rows = initial_order(rows, waiting)
        self.adding = adding
        self.estimates = estimates or {}
        self.checked: set[str] = {r.title_id for r in self.rows if r.checked and r.enabled}
        t = self.m.t
        self.setWindowTitle(t('queue.title'))
        self.setMinimumSize(640, 500)
        self.setStyleSheet(style.STYLESHEET)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(14)
        title = QLabel(t('queue.title'))
        title.setStyleSheet('font-size: 20px; font-weight: 800;')
        lay.addWidget(title)
        note = QLabel(t('queue.note') + ' ' + t('queue.orderNote'))
        note.setObjectName('muted')
        note.setWordWrap(True)
        lay.addWidget(note)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.scroll, 1)

        foot = QHBoxLayout()
        self.total_lbl = QLabel('')
        self.total_lbl.setObjectName('muted')
        foot.addWidget(self.total_lbl)
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
        self._render()

    @property
    def chosen(self) -> list[str]:
        """The ticked games, in the order shown: the build order."""
        return [r.title_id for r in self.rows if r.title_id in self.checked]

    def _status_text(self, row: QueueRow) -> str:
        t = self.m.t
        text = t('queue.statusVersion', row.supported) if row.status == 'version' else t('queue.status.' + row.status)
        est = format_duration(self.estimates.get(row.title_id))
        return f'{text} · {est}' if est and row.status not in ('running', 'missing', 'mac') else text

    def _render(self) -> None:
        """(Re)build the rows: a switch, the game with its place in the queue when ticked, and ▲ / ▼ to move it."""
        keep = self.scroll.verticalScrollBar().value()
        group = CardGroup()
        movable = [r.title_id for r in self.rows if r.enabled]
        place = {tid: i + 1 for i, tid in enumerate(self.chosen)}
        for idx, row in enumerate(self.rows):
            if idx:
                group.add_divider()
            w = QWidget()
            rl = QHBoxLayout(w)
            rl.setContentsMargins(18, 10, 12, 10)
            rl.setSpacing(12)
            sw = LauncherSwitch(checked=row.title_id in self.checked)
            sw.setEnabled(row.enabled)
            sw.toggled.connect(lambda on, tid=row.title_id: self._toggle(tid, on))
            rl.addWidget(sw)
            col = QVBoxLayout()
            col.setSpacing(2)
            name = QLabel(f'{place[row.title_id]} · {row.name}' if row.title_id in place else row.name)
            name.setObjectName('rowTitle')
            status = QLabel(self._status_text(row))
            status.setObjectName('muted')
            status.setWordWrap(True)
            if row.status == 'version':
                status.setStyleSheet(f'color: {style.AMBER};')
            col.addWidget(name)
            col.addWidget(status)
            rl.addLayout(col, 1)
            if row.enabled:
                pos = movable.index(row.title_id)
                for text, step, tip in (('▲', -1, 'queue.moveUp'), ('▼', 1, 'queue.moveDown')):
                    b = QPushButton(text)
                    b.setObjectName('ghost')
                    b.setFixedSize(34, 30)
                    b.setToolTip(self.m.t(tip))
                    b.setEnabled(0 <= pos + step < len(movable))
                    b.clicked.connect(lambda _=False, tid=row.title_id, s=step: self._move(tid, s))
                    rl.addWidget(b)
            group.add_row(w)
        self.scroll.setWidget(group)
        self.scroll.verticalScrollBar().setValue(keep)
        n = len(self.checked)
        known = [self.estimates.get(tid) for tid in self.checked]
        total = sum(e for e in known if e)
        self.total_lbl.setText(self.m.t('queue.total', format_duration(total)) if total else '')
        self.start_btn.setText(self.m.t('queue.add' if self.adding else 'queue.start', n))
        self.start_btn.setEnabled(n > 0)

    def _toggle(self, title_id: str, on: bool) -> None:
        if on:
            self.checked.add(title_id)
        else:
            self.checked.discard(title_id)
        QTimer.singleShot(0, self._render)   # not now: the switch that called is one of the rows rebuilt

    def _move(self, title_id: str, step: int) -> None:
        """Swap a game with the next movable one above (step -1) or below (step 1)."""
        movable = [i for i, r in enumerate(self.rows) if r.enabled]
        at = next((k for k, i in enumerate(movable) if self.rows[i].title_id == title_id), None)
        to = (at if at is not None else -2) + step
        if at is None or not 0 <= to < len(movable):   # a row that cannot move, or already at that end
            return
        a, b = movable[at], movable[to]
        self.rows[a], self.rows[b] = self.rows[b], self.rows[a]
        QTimer.singleShot(0, self._render)   # not now: the arrow that called is one of the rows rebuilt
