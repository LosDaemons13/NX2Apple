"""The "Send to iPhone (Wi-Fi)" window: runs wifi_share.ShareServer while it is open and says what to type on the iPhone."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import platform_util as pu
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
        self._ipa_version: str | None = None   # the launcher version that made the IPA, read with its staleness
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
        # an IPA exported by an older launcher carries its older iPhone app (no Receive from PC, for one)
        stale_row = QHBoxLayout()
        self.stale_lbl = QLabel(t('wifi.stale'))
        self.stale_lbl.setWordWrap(True)
        self.stale_lbl.setStyleSheet(f'color: {style.AMBER};')
        stale_row.addWidget(self.stale_lbl, 1)
        self.remake_btn = QPushButton(t('wifi.remake'))
        self.remake_btn.setObjectName('ghost')
        self.remake_btn.clicked.connect(self._remake_ipa)
        stale_row.addWidget(self.remake_btn)
        c1.addLayout(stale_row)
        self._remake: dict | None = None
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
        stale = ipa is not None and self._ipa_is_stale(ipa)
        busy = self._remake is not None or self._export_elsewhere()
        error = getattr(self, '_remake_error', '')
        self.stale_lbl.setText(t('wifi.remaking') if busy else (t('wifi.remakeFailed', error) if error else t('wifi.stale')))
        self.stale_lbl.setVisible(stale or busy or bool(error))
        self.remake_btn.setVisible(stale and not busy)
        self.remake_btn.setEnabled(not self.m.running)
        if ipa is None:
            self.ipa_status.setText(t('wifi.noIpa'))
        else:
            st = ipa.stat()
            status = t('wifi.ipaStatus', _gb(st.st_size), time.strftime('%H:%M', time.localtime(st.st_mtime)))
            version = self._ipa_version
            self.ipa_status.setText(f"{status}\n{t('wifi.ipaVersion', version)}" if version else status)
        games = ws.shared_games(self.m.library.games)
        self.games_label.setText(', '.join(f'{g.name} ({_gb(sum(s for _, s in g.files()))})' for g in games)
                                 if games else t('wifi.noData'))

    def _ipa_is_stale(self, ipa: Path) -> bool:
        """Whether the IPA's iPhone app is not the one this launcher ships (exported by another version)."""
        from .win import shell_export as se
        key = (str(ipa), ipa.stat().st_mtime)
        if getattr(self, '_stale_key', None) != key:
            tpl = se.find_shell_template(self.m.engine_path, root=self.m.shell_cache_path)
            current = se.shell_template_id(tpl) if tpl is not None else None
            self._stale = current is not None and se.ipa_template_id(ipa) != current
            self._ipa_version = se.ipa_app_version(ipa)
            self._stale_key = key
        return self._stale

    @staticmethod
    def _export_elsewhere() -> bool:
        """An export of the IPA runs now (this window's from before it was closed, a GitHub republish, a build's end):
        the window says the IPA is being made instead of offering a second export."""
        if not pu.IS_WIN:
            return False
        from .win import shell_export as se
        return se.export_busy()

    def _remake_ipa(self) -> None:
        """Export the IPA again with this launcher's iPhone app and the games already built: no build, a few minutes."""
        from .win import shell_export as se
        if self._remake is not None or self.m.running or self._export_elsewhere():
            self._refresh()
            return
        root, engine = self.m.shell_cache_path, self.m.engine_path
        python_exe, banners = self.m.python_path or '', self.m.artwork.banners_dir
        custom = dict(self.m.artwork.custom_paths)
        job: dict = {'done': False, 'error': ''}
        self._remake = job

        def work() -> None:
            try:
                library = se.ShellLibrary.load(root)
                first = next((g for g in library.games if Path(g.framework).is_dir()), None)
                if first is None:
                    job['error'] = self.m.t('wifi.noIpa')
                    return
                ok, _out, msg, _notes = se.export_shell(
                    root=root, repo=engine, framework=first.framework, title_id=first.title_id, name=first.name,
                    python_exe=python_exe, banners_dir=banners, picked_artwork=custom.get(first.title_id.upper()),
                    t_func=self.m.t)
                if not ok:
                    job['error'] = msg
            except Exception as e:   # a thread must never take the window down
                job['error'] = str(e) or type(e).__name__
            finally:
                job['done'] = True

        threading.Thread(target=work, name='remake-ipa', daemon=True).start()
        self._refresh()

    def _tick(self) -> None:
        a = self.server.activity
        with a.lock:
            sending = list(a.sending.values())
        if sending:
            self.activity.setText('\n'.join(self.m.t('wifi.sending', rel, f'{sent * 100 // max(total, 1)}')
                                            for rel, sent, total in sending))
        else:
            self.activity.setText('')
        job = self._remake
        if job is not None and job['done']:
            self._remake = None
            self._stale_key = None
            self._remake_error = job['error']
            self._refresh()
        elif int(time.time()) % 10 == 0:   # a build of the queue may have written a new IPA or a game's data
            self._refresh()

    def _copy(self, text: str) -> None:
        if text:
            QGuiApplication.clipboard().setText(text)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.server.stop()
        super().closeEvent(event)
