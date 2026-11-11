"""Box art for the iPhone shell's game cases.

The player picks a portrait picture of a game's case (its front cover) in the library. It is kept as
`<state dir>/covers/<title ID>.<ext>`, beside the banners, and the shared-app export copies it into the game's framework
as `cover.<ext>`, where the shell's catalogue finds it (`GameCatalogue`, `coverURL`).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

EXTENSIONS = ('png', 'jpg', 'jpeg', 'heic', 'webp')


def covers_dir(state_dir: str | os.PathLike) -> Path:
    return Path(state_dir) / 'covers'


def covers_dir_beside(banners_dir: str | os.PathLike | None) -> Path | None:
    """The covers folder next to the banners folder the export already gets."""
    return Path(banners_dir).parent / 'covers' if banners_dir else None


def find(folder: str | os.PathLike | None, title_id: str) -> Path | None:
    if not folder:
        return None
    tid = title_id.strip().upper()
    for ext in EXTENSIONS:
        p = Path(folder) / f'{tid}.{ext}'
        if p.is_file():
            return p
    return None


def find_in_framework(framework: str | os.PathLike) -> Path | None:
    """The `cover.<ext>` an earlier export put into the game's framework."""
    for ext in EXTENSIONS:
        p = Path(framework) / f'cover.{ext}'
        if p.is_file():
            return p
    return None


def clear(folder: str | os.PathLike, title_id: str) -> None:
    tid = title_id.strip().upper()
    for ext in EXTENSIONS:
        try:
            (Path(folder) / f'{tid}.{ext}').unlink(missing_ok=True)
        except OSError:
            pass


def set_cover(folder: str | os.PathLike, title_id: str, source: str | os.PathLike) -> Path:
    """Keep a copy of `source` as the game's box art, replacing any earlier one. Raises OSError or ValueError."""
    src = Path(source)
    ext = src.suffix.lstrip('.').lower()
    if ext not in EXTENSIONS:
        raise ValueError(f'not a picture the iPhone reads: {src.name}')
    Path(folder).mkdir(parents=True, exist_ok=True)
    clear(folder, title_id)
    dest = Path(folder) / f'{title_id.strip().upper()}.{ext}'
    shutil.copy2(src, dest)
    return dest


def place(title_id: str, framework: str | os.PathLike, folder: str | os.PathLike | None) -> str | None:
    """Copy the game's box art into `<framework>/cover.<ext>`, or remove a stale one. Returns the source used."""
    fw = Path(framework)
    for ext in EXTENSIONS:
        try:
            (fw / f'cover.{ext}').unlink(missing_ok=True)
        except OSError:
            pass
    source = find(folder, title_id)
    if source is None or not fw.is_dir():
        return None
    ext = source.suffix.lstrip('.').lower()
    try:
        shutil.copy2(source, fw / f'cover.{ext}')
        return str(source)
    except OSError:
        return None
