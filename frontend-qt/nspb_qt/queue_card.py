"""The build queue on the build page (BuildQueueCard.swift on the Mac): what was built, what is being built, what waits.

Each waiting game can be moved (▲ / ▼) or taken out (Remove); Cancel empties what waits after a question, and the build
under way goes on (Stop in the activity bar ends it, and the queue with it). The window owns the queue (model.queue) and
calls refresh() whenever its state may have changed; the rows are rebuilt only when the queue changed, so a click on a row
is never lost to a progress update.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from . import style
from .build_estimate import format_duration
from .widgets import CardGroup

if TYPE_CHECKING:
    from .model import Model

STATUS_COLORS = {'done': style.GREEN, 'running': style.AMBER, 'failed': style.RED}
OUTCOME_STATUS = {'ok': 'done', 'failed': 'failed', 'skipped': 'skipped'}


class BuildQueueCard(CardGroup):
    def __init__(self, model: 'Model', *, on_select: Callable[[], None], on_change: Callable[[], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.m = model
        self.on_select = on_select
        self.on_change = on_change
        self._shown: tuple | None = None
        self.hide()

    # ---------------------------------------------------------------- state

    def _name(self, title_id: str) -> str:
        game = next((g for g in self.m.library.games if g.title_id.upper() == title_id.upper()), None)
        return game.name if game else title_id

    def _estimate(self, title_id: str) -> str:
        game = next((g for g in self.m.library.games if g.title_id.upper() == title_id.upper()), None)
        try:
            return format_duration(self.m.estimate_for(game)) if game else ''
        except Exception:   # an estimate never keeps the queue from showing
            return ''

    def entries(self) -> list[tuple[str, str]]:
        """(title ID, status) in the order the queue runs: built, being built, waiting."""
        q = self.m.queue
        out = [(tid, OUTCOME_STATUS.get(outcome, 'failed')) for tid, outcome in q.results]
        if q.current:
            out.append((q.current, 'running'))
        out += [(tid, 'queued') for tid in q.waiting]
        return out

    def wanted(self) -> bool:
        """Shown while the queue runs, and after it while no other build runs (its outcomes)."""
        q = self.m.queue
        return q.active or (bool(q.results) and not self.m.running)

    def refresh(self, force: bool = False) -> None:
        state = (self.wanted(), tuple(self.entries()), self.m.t('queue.title'))
        if state == self._shown and not force:
            return
        self._shown = state
        self.setVisible(state[0])
        if state[0]:
            self._render()

    # ---------------------------------------------------------------- rows

    def _clear_rows(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _render(self) -> None:
        t = self.m.t
        waiting = list(self.m.queue.waiting)
        self.set_title(t('queue.title') + (' · ' + t('queue.count', len(waiting)) if waiting else ''))
        self._clear_rows()
        for i, (tid, status) in enumerate(self.entries()):
            if i:
                self.add_divider()
            self.add_row(self._row(tid, status, waiting))
        self.add_divider()
        self.add_row(self._footer(len(waiting)))

    def _row(self, title_id: str, status: str, waiting: list[str]) -> QWidget:
        t = self.m.t
        w = QWidget()
        rl = QHBoxLayout(w)
        rl.setContentsMargins(18, 10, 12, 10)
        rl.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = self._name(title_id)
        place = next((i + 1 for i, tid in enumerate(waiting) if tid.upper() == title_id.upper()), 0) if status == 'queued' else 0
        title = QLabel(f'{place} · {name}' if place else name)
        title.setObjectName('rowTitle')
        title.setWordWrap(True)
        col.addWidget(title)
        text = t('queue.status.' + status)
        est = self._estimate(title_id) if status == 'queued' else ''
        st = QLabel(f'{text} · {est}' if est else text)
        if status in STATUS_COLORS:
            st.setStyleSheet(f'color: {STATUS_COLORS[status]}; font-weight: 600;')
        else:
            st.setObjectName('muted')
        col.addWidget(st)
        rl.addLayout(col, 1)
        if status == 'queued':
            for text_, step, tip, named in (('▲', -1, 'queue.moveUp', 'queue.moveUpNamed'), ('▼', 1, 'queue.moveDown', 'queue.moveDownNamed')):
                b = QPushButton(text_)
                b.setObjectName('ghost')
                b.setFixedSize(34, 30)
                b.setToolTip(t(tip))
                b.setAccessibleName(t(named, name))
                b.setEnabled(0 <= place - 1 + step < len(waiting))
                b.clicked.connect(lambda _=False, tid=title_id, s=step: self._move(tid, s))
                rl.addWidget(b)
            rm = QPushButton(t('queue.remove'))
            rm.setObjectName('ghost')
            rm.setToolTip(t('queue.removeNamed', name))
            rm.setAccessibleName(t('queue.removeNamed', name))
            rm.clicked.connect(lambda _=False, tid=title_id: self._remove(tid))
            rl.addWidget(rm)
        return w

    def _footer(self, n_waiting: int) -> QWidget:
        t = self.m.t
        w = QWidget()
        fl = QHBoxLayout(w)
        fl.setContentsMargins(18, 10, 12, 10)
        self.cancel_btn = QPushButton(t('queue.cancel') + (' · ' + t('queue.count', n_waiting) if n_waiting else ''))
        self.cancel_btn.setObjectName('ghost')
        self.cancel_btn.setEnabled(n_waiting > 0)
        self.cancel_btn.clicked.connect(self._cancel_waiting)
        fl.addWidget(self.cancel_btn)
        fl.addStretch(1)
        self.select_btn = QPushButton(t('queue.select'))
        self.select_btn.setObjectName('ghost')
        self.select_btn.clicked.connect(self.on_select)
        fl.addWidget(self.select_btn)
        return w

    # ---------------------------------------------------------------- actions

    def _changed(self) -> None:
        # not now: the button that called is one of the rows rebuilt
        QTimer.singleShot(0, lambda: (self.refresh(), self.on_change()))

    def _move(self, title_id: str, step: int) -> None:
        if self.m.queue.move(title_id, step):
            self._changed()

    def _remove(self, title_id: str) -> None:
        if self.m.queue.remove(title_id):
            self.m.log(self.m.t('queue.added', len(self.m.queue.waiting)) + '\n')
            self._changed()

    def confirm_cancel(self, n: int) -> bool:
        """Ask before emptying what waits (the build under way and the outcomes stay)."""
        t = self.m.t
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(t('queue.title'))
        box.setText(t('queue.cancelConfirm', n))
        drop = box.addButton(t('queue.cancel'), QMessageBox.DestructiveRole)
        keep = box.addButton(t('queue.keep'), QMessageBox.RejectRole)
        box.setDefaultButton(keep)
        box.exec()
        return box.clickedButton() is drop

    def _cancel_waiting(self) -> None:
        n = len(self.m.queue.waiting)
        if n and self.confirm_cancel(n):
            self.m.queue.drop_waiting()
            self.m.log(self.m.t('queue.added', 0) + '\n')
            self._changed()
