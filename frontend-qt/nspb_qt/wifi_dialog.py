"""The "Send to iPhone (Wi-Fi)" window: runs wifi_share.ShareServer while it is open and says what to type on the iPhone."""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import style
from . import wifi_share as ws
from .widgets import CardGroup

if TYPE_CHECKING:
    from .model import Model


def _gb(n: int) -> str:
    return f'{n / 1e9:.1f} GB' if n >= 1e8 else f'{n / 1e6:.0f} MB'


class WifiShareDialog(QDialog):
    def __init__(self, model: 'Model', ipa_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.m = model
        self.ipa_path = Path(ipa_path)
        t = self.m.t
        self.setWindowTitle(t('wifi.title'))
        self.setMinimumSize(640, 560)
        self.setStyleSheet(style.STYLESHEET)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.server = ws.ShareServer(ipa=self._ipa, games=lambda: ws.shared_games(self.m.library.games), page=self._page)
        self.error = ''
        try:
            self.server.start()
        except OSError as e:
            self.error = str(e)
        hosts = ws.local_addresses() or ['127.0.0.1']
        self.base = self.server.address(hosts[0]) if self.server.running else ''

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(14)
        title = QLabel(t('wifi.title'))
        title.setStyleSheet('font-size: 20px; font-weight: 800;')
        lay.addWidget(title)
        note = QLabel(t('wifi.note') if not self.error else t('wifi.failed', self.error))
        note.setObjectName('muted')
        note.setWordWrap(True)
        lay.addWidget(note)

        group = CardGroup()
        # 1. the app
        r1 = QWidget()
        c1 = QVBoxLayout(r1)
        c1.setContentsMargins(18, 14, 18, 14)
        c1.setSpacing(6)
        h1 = QLabel(t('wifi.ipaTitle'))
        h1.setObjectName('rowTitle')
        c1.addWidget(h1)
        self.ipa_status = QLabel('')
        self.ipa_status.setObjectName('muted')
        self.ipa_status.setWordWrap(True)
        c1.addWidget(self.ipa_status)
        how1 = QLabel(t('wifi.ipaHow'))
        how1.setWordWrap(True)
        c1.addWidget(how1)
        row = QHBoxLayout()
        self.ipa_url = QLabel(self.base + 'NX2Apple.ipa' if self.base else '—')
        self.ipa_url.setObjectName('mono')
        self.ipa_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ipa_url.setWordWrap(True)
        row.addWidget(self.ipa_url, 1)
        copy1 = QPushButton(t('wifi.copy'))
        copy1.setObjectName('ghost')
        copy1.clicked.connect(lambda: self._copy(self.base + 'NX2Apple.ipa'))
        row.addWidget(copy1)
        c1.addLayout(row)
        group.add_row(r1)
        group.add_divider()
        # 2. the games' data
        r2 = QWidget()
        c2 = QVBoxLayout(r2)
        c2.setContentsMargins(18, 14, 18, 14)
        c2.setSpacing(6)
        h2 = QLabel(t('wifi.dataTitle'))
        h2.setObjectName('rowTitle')
        c2.addWidget(h2)
        how2 = QLabel(t('wifi.dataHow'))
        how2.setWordWrap(True)
        c2.addWidget(how2)
        row2 = QHBoxLayout()
        self.address = QLabel(self.base or '—')
        self.address.setObjectName('mono')
        self.address.setStyleSheet('font-size: 18px; font-weight: 700;')
        self.address.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row2.addWidget(self.address, 1)
        copy2 = QPushButton(t('wifi.copy'))
        copy2.setObjectName('ghost')
        copy2.clicked.connect(lambda: self._copy(self.base))
        row2.addWidget(copy2)
        c2.addLayout(row2)
        self.games_label = QLabel('')
        self.games_label.setObjectName('muted')
        self.games_label.setWordWrap(True)
        c2.addWidget(self.games_label)
        group.add_row(r2)
        lay.addWidget(group)

        self.activity = QLabel('')
        self.activity.setObjectName('muted')
        self.activity.setWordWrap(True)
        lay.addWidget(self.activity)
        lay.addStretch(1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        close = QPushButton(t('wifi.stop'))
        close.setObjectName('creamPill')
        close.clicked.connect(self.close)
        foot.addWidget(close)
        lay.addLayout(foot)

        self._refresh()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ---- what is offered
    def _ipa(self) -> Path | None:
        return self.ipa_path if self.ipa_path.is_file() else None

    def _page(self, cat: dict, base: str) -> str:
        t = self.m.t
        return ws.render_page(cat, {
            'title': t('wifi.page.title'), 'ipa': t('wifi.page.ipa'), 'noIpa': t('wifi.page.noIpa'),
            'flare': t('wifi.page.flare'), 'data': t('wifi.dataTitle'), 'dataNote': t('wifi.page.dataNote'),
            'none': t('wifi.page.none'),
        }, base)

    def _refresh(self) -> None:
        t = self.m.t
        ipa = self._ipa()
        if ipa is None:
            self.ipa_status.setText(t('wifi.noIpa'))
        else:
            st = ipa.stat()
            self.ipa_status.setText(t('wifi.ipaStatus', _gb(st.st_size), time.strftime('%H:%M', time.localtime(st.st_mtime))))
        games = ws.shared_games(self.m.library.games)
        self.games_label.setText(', '.join(f'{g.name} ({_gb(sum(s for _, s in g.files()))})' for g in games)
                                 if games else t('wifi.noData'))

    def _tick(self) -> None:
        a = self.server.activity
        with a.lock:
            sending = list(a.sending.values())
        if sending:
            self.activity.setText('\n'.join(self.m.t('wifi.sending', rel, f'{sent * 100 // max(total, 1)}')
                                            for rel, sent, total in sending))
        else:
            self.activity.setText('')
        if int(time.time()) % 10 == 0:   # a build of the queue may have written a new IPA or a game's data
            self._refresh()

    def _copy(self, text: str) -> None:
        if text:
            QGuiApplication.clipboard().setText(text)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.server.stop()
        super().closeEvent(event)
