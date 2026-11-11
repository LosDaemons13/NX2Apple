"""The folder the build script reads when the picked game files live in more than one folder (#132).

The script keys a provisional profile's shader split and shader build on the files' size and
modification time and on the profile's path (<input folder>/<title ID>_build/profile), so the folder
must be the same one on every build of a game: it sits in the game's build folder, is never deleted
after a build, and holds exactly the current selection. The build's own folders beside the files
(<title ID>_build, <title ID>_survey) are left alone.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

FOLDER_NAME = 'staging'
GAME_SUFFIXES = {'.nsp', '.xci', '.nsz', '.xcz'}


def folder(work_dir: str) -> str:
    return str(Path(work_dir, FOLDER_NAME))


def staged_name(name: str) -> str:
    """The name a file has in the staging folder: a game file keeps its name with the extension in lowercase. The script
    finds packages with *.nsp (and .xci, .nsz, .xcz) and that glob is case-sensitive, so Game [0100F2C0115B6000].NSP
    was not found ("no NSP with a readable title ID", #554)."""
    p = Path(name)
    suffix = p.suffix
    if suffix.lower() in GAME_SUFFIXES and suffix != suffix.lower():
        return p.stem + suffix.lower()
    return name


def needs_lowercase_name(path: str) -> bool:
    """A game file with an upper or mixed case extension: the script would not find it as it is."""
    name = Path(path).name
    return staged_name(name) != name


def _same(src: str, dst: Path) -> bool:
    """dst is already src: the same file, or a copy with its size and date."""
    try:
        if os.path.samefile(src, dst):
            return True
        a, b = os.stat(src), os.stat(dst)
        return a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns
    except OSError:
        return False


class StagingError(OSError):
    """A game file could be neither linked nor copied into the staging folder (a full disk, most often)."""

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f'{name}: {reason}')
        self.name = name
        self.reason = reason


def _is_link_of(src: str, dst: Path) -> bool:
    try:
        return os.path.samefile(src, dst)
    except OSError:
        return False


def _relink(src: str, dst: Path) -> None:
    """Turn a copy an earlier build left into a hard link, which gives its space back. Kept as it is when that fails."""
    tmp = dst.with_name(dst.name + '.link')
    try:
        tmp.unlink(missing_ok=True)
        os.link(src, tmp)
        os.replace(tmp, dst)
    except OSError:
        tmp.unlink(missing_ok=True)


def sync(files: list[str], into: str, *, hard_links: bool = True) -> int:
    """Make `into` hold exactly `files` (by file name), with their dates. Returns how many were staged.

    A hard link first (no space, no time; NTFS has them too), a copy where the volume cannot link (exFAT, another
    drive). A file that can be neither raises StagingError: it used to be skipped without a word, and the script then
    said "no base game NSP found" for a 14.6 GB game that did not fit on a full disk.
    """
    root = Path(into)
    root.mkdir(parents=True, exist_ok=True)
    wanted = {staged_name(Path(f).name): f for f in files if f}
    for entry in root.iterdir():   # a stale entry from an earlier selection goes: only game files and links
        if entry.name.endswith('.link'):
            entry.unlink(missing_ok=True)   # left by a _relink cut short
            continue
        if entry.is_symlink() or (entry.is_file() and entry.suffix.lower() in GAME_SUFFIXES):
            src = wanted.get(entry.name)
            if src and entry.exists() and _same(src, entry):
                if hard_links and not entry.is_symlink() and not _is_link_of(src, entry):
                    _relink(src, entry)
                continue
            entry.unlink(missing_ok=True)
    staged = 0
    for name, src in wanted.items():
        dst = root / name
        if dst.exists() and _same(src, dst):
            staged += 1
            continue
        try:
            if not hard_links:
                raise OSError
            os.link(src, dst)
        except OSError:
            try:
                shutil.copy2(src, dst)   # copy2 keeps the modification date
            except OSError as e:
                dst.unlink(missing_ok=True)   # a copy cut short is not a game file
                raise StagingError(name, e.strerror or str(e)) from e
        staged += 1
    return staged
