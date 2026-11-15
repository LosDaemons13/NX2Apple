"""Dialogs for game queues and shell IPA selection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from . import style
from .build_estimate import format_duration
from .build_queue import QueueRow
from .widgets import CardGroup, LauncherSwitch

if TYPE_CHECKING:
    from .model import Model
    from .win import shell_export as se


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


# ---------------------------------------------------------------------------
# Shell IPA Selection Dialog: pick which already-built games go into the shared IPA
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShellGameRow:
    title_id: str
    name: str
    framework: str
    has_framework: bool
    checked: bool


class ShellIpaSelectionDialog(QDialog):
    """Select which built games to include in the shared IPA. No rebuild — just re-pack."""

    def __init__(self, model: 'Model', parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.m = model
        t = self.m.t
        self.setWindowTitle(t('shell.selectTitle'))
        self.setMinimumSize(560, 440)
        self.setStyleSheet(style.STYLESHEET)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(14)
        title = QLabel(t('shell.selectTitle'))
        title.setStyleSheet('font-size: 20px; font-weight: 800;')
        lay.addWidget(title)
        note = QLabel(t('shell.selectNote'))
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
        self.export_btn = QPushButton('')
        self.export_btn.setObjectName('creamPill')
        self.export_btn.clicked.connect(self.accept)
        foot.addWidget(self.export_btn)
        lay.addLayout(foot)

        # Load games from shell cache
        from .win import shell_export as se
        root = Path(self.m.shell_cache_path)
        library = se.ShellLibrary.load(root)
        self.rows: list[ShellGameRow] = []
        for g in library.games:
            fw_exists = Path(g.framework).is_dir()
            self.rows.append(ShellGameRow(
                title_id=g.title_id,
                name=g.name or g.title_id,
                framework=g.framework,
                has_framework=fw_exists,
                checked=fw_exists,   # tick only complete frameworks by default
            ))
        self._render()

    @property
    def chosen(self) -> list[ShellGameRow]:
        return [r for r in self.rows if r.checked and r.has_framework]

    def _render(self) -> None:
        keep = self.scroll.verticalScrollBar().value()
        group = CardGroup()
        for idx, row in enumerate(self.rows):
            if idx:
                group.add_divider()
            w = QWidget()
            rl = QHBoxLayout(w)
            rl.setContentsMargins(18, 10, 12, 10)
            rl.setSpacing(12)
            sw = LauncherSwitch(checked=row.checked)
            sw.setEnabled(row.has_framework)
            sw.toggled.connect(lambda on, tid=row.title_id: self._toggle(tid, on))
            rl.addWidget(sw)
            col = QVBoxLayout()
            col.setSpacing(2)
            name = QLabel(row.name)
            name.setObjectName('rowTitle')
            col.addWidget(name)
            if row.has_framework:
                status = QLabel(self.m.t('shell.selectReady'))
                status.setObjectName('muted')
            else:
                status = QLabel(self.m.t('shell.selectMissing'))
                status.setObjectName('muted')
                status.setStyleSheet(f'color: {style.AMBER};')
            col.addWidget(status)
            rl.addLayout(col, 1)
            group.add_row(w)
        self.scroll.setWidget(group)
        self.scroll.verticalScrollBar().setValue(keep)
        n = len(self.chosen)
        self.total_lbl.setText(self.m.t('shell.selectTotal', n) if n else '')
        self.export_btn.setText(self.m.t('shell.selectExport', n))
        self.export_btn.setEnabled(n > 0)
        self.m.log(f'select-dialog: render done, chosen={[(r.title_id, r.checked) for r in self.chosen]}\n')

    def _toggle(self, title_id: str, on: bool) -> None:
        for row in self.rows:
            if row.title_id == title_id:
                # dataclass is frozen, so replace in list
                idx = self.rows.index(row)
                self.rows[idx] = ShellGameRow(
                    title_id=row.title_id,
                    name=row.name,
                    framework=row.framework,
                    has_framework=row.has_framework,
                    checked=on,
                )
                break
        self.m.log(f'select-dialog: toggled {title_id}={on}\n')
        QTimer.singleShot(0, self._render)

    def accept(self) -> None:
        self.m.log(f'select-dialog: accept, chosen={[(r.title_id, r.name) for r in self.chosen]}\n')
        super().accept()
