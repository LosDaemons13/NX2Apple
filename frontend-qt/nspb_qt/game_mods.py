"""A game's mods in the Windows launcher: one folder each in the game's data folder, `games/<title ID>/mods/<mod>`.

That is the folder the iPhone app reads (frontend-ios GameMods.swift, `Documents/games/<title ID>/mods`), and the Wi-Fi share sends
the data folder as it is, so the mods go with the game data. Two kinds:

- RomFS mods (`romfs/`, `atmosphere/contents/<title ID>/romfs`, `contents/<title ID>/romfs`): the iPhone app reads them at every
  start (DM_ROMFS_OVERLAY). No new build, only a new send of the game data.
- Code mods (`.pchtxt` and `.ips` in `exefs/`, `exefs_patches/<name>/`, `atmosphere/exefs_patches/<name>/`): the build hands the
  folder to the engine (`--mods`), which writes the patches into the module whose build ID they name before the rewrite
  (engine dm/tools/exefs_mods.py). They take effect at the next build, and only for the version they were made for.

A mod that replaces modules (exlaunch: `exefs/subsdk*`, `exefs/main.npdm`) cannot be used. A dot before a mod's name switches it
off: the engine, the iPhone app and the Wi-Fi share all skip such a folder. Pure stdlib, no Qt.
"""
from __future__ import annotations

import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

ROMFS_DIRS = ('romfs',)
CODE_DIRS = ('exefs', 'exefs_patches')
MODULE_FILE = re.compile(r'(main|rtld|sdk|subsdk\d+)(\.npdm)?$', re.IGNORECASE)
NSOBID = re.compile(r'^\s*@nsobid-([0-9A-Fa-f]+)', re.MULTILINE)
CONTENTS = re.compile(r'(?:^|/)(?:atmosphere/)?contents/([0-9A-Fa-f]{16})$', re.IGNORECASE)


def norm_id(text: str) -> str | None:
    """A build ID as the engine keys on it: lowercase hex of its first 16 bytes, a shorter one padded with zeros."""
    text = text.strip().lower()
    if not text or not re.fullmatch(r'[0-9a-f]+', text):
        return None
    return (text + '0' * 32)[:32]


@dataclass
class Mod:
    name: str                      # without the dot that switches it off
    path: Path
    enabled: bool
    romfs: bool = False
    code_files: list[Path] = field(default_factory=list)
    code_ids: set[str] = field(default_factory=set)   # the build IDs its code patches name
    replaced: list[str] = field(default_factory=list)  # files that replace modules (exlaunch)

    @property
    def kind(self) -> str:
        """romfs, code, both, unsupported (only modules it would replace) or empty"""
        if self.code_files and self.romfs:
            return 'both'
        if self.code_files:
            return 'code'
        if self.romfs:
            return 'romfs'
        return 'unsupported' if self.replaced else 'empty'

    def fits(self, build_id: str | None) -> bool | None:
        """Whether its code patches are for build_id (the game's main as built), None when either is unknown."""
        if not self.code_ids or not build_id:
            return None
        return norm_id(build_id) in self.code_ids


def data_folder(archive_path: str, output_dir: str, base_input: str, title_id: str) -> Path | None:
    """The game's data folder: the one its build left, else where the next build puts it (model.py: <output>/games/<title ID>)."""
    if archive_path:
        return Path(archive_path)
    root = output_dir or (os.path.dirname(base_input) if base_input else '')
    return Path(root, 'games', title_id.upper()) if root else None


def folder_of(game) -> Path | None:
    """The mods folder of a library game (library.LibraryGame)."""
    d = data_folder(game.archive_path if game.has_archive else '', game.output_dir, (game.inputs.get('base') or [''])[0], game.title_id)
    return d / 'mods' if d else None


def _code_files(mod: Path) -> list[Path]:
    dirs = []
    if (mod / 'exefs').is_dir():
        dirs.append(mod / 'exefs')
    for sub in (mod / 'exefs_patches', mod / 'atmosphere' / 'exefs_patches'):
        if sub.is_dir():
            dirs += sorted((d for d in sub.iterdir() if d.is_dir()), key=lambda p: p.name.lower())
    return [f for d in dirs for f in sorted(d.iterdir(), key=lambda p: p.name.lower())
            if f.is_file() and f.suffix.lower() in ('.pchtxt', '.ips')]


def _build_id(f: Path) -> str | None:
    if f.suffix.lower() == '.ips':
        return norm_id(f.stem)
    try:
        m = NSOBID.search(f.read_text(encoding='utf-8', errors='replace'))
    except OSError:
        return None
    return norm_id(m.group(1)) if m else None


def read(mod: Path, title_id: str) -> Mod:
    """What a mod folder holds."""
    enabled = not mod.name.startswith('.')
    tid = title_id.upper()
    romfs = any((mod / p).is_dir() for p in ('romfs', f'atmosphere/contents/{tid}/romfs', f'contents/{tid}/romfs'))
    files = _code_files(mod)
    ids = {b for b in (_build_id(f) for f in files) if b}
    try:
        replaced = sorted(f.name for f in (mod / 'exefs').iterdir() if f.is_file() and MODULE_FILE.match(f.name))
    except OSError:
        replaced = []
    return Mod(mod.name.lstrip('.'), mod, enabled, romfs, files, ids, replaced)


def list_mods(folder: Path | None, title_id: str) -> list[Mod]:
    """The game's mods in name order, the order the engine and the iPhone app take them in."""
    if not folder or not folder.is_dir():
        return []
    return [read(d, title_id) for d in sorted((d for d in folder.iterdir() if d.is_dir() and not d.is_symlink()),
                                              key=lambda p: p.name.lstrip('.').lower())]


def has_code_mods(folder: Path | None, title_id: str) -> bool:
    """Whether a switched-on mod has code patches: the build then passes --mods."""
    return any(m.enabled and m.code_files for m in list_mods(folder, title_id))


def set_enabled(mod: Mod, on: bool, title_id: str) -> Mod:
    """Switch a mod on or off by the dot before its folder's name; returns it as it is now."""
    want = mod.path.with_name(('' if on else '.') + mod.name)
    if want != mod.path:
        if want.exists():
            raise OSError(f'{want} already exists')
        mod.path.rename(want)
    return read(want, title_id)


def remove(mod: Mod) -> None:
    shutil.rmtree(mod.path)


def _safe(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip().strip('.')
    return name or 'mod'


def _roots(dirs: set[str], files: set[str], title_id: str) -> list[str]:
    """The folders of an archive (posix paths, '' for its top) that are mods: they hold exefs/, exefs_patches/ or romfs/ directly,
    or the Atmosphere layout (atmosphere/contents/<title ID>/...) below them. A contents/ folder of another game is left out."""
    marks = set(ROMFS_DIRS) | set(CODE_DIRS)
    found: list[str] = []
    for d in sorted(dirs | {''}):
        kids = {PurePosixPath(x).name.lower() for x in dirs if str(PurePosixPath(x).parent) == (d or '.')}
        if not (kids & marks):
            continue
        m = CONTENTS.search(d)
        if m:
            if m.group(1).upper() != title_id.upper():
                continue
            d = d[:m.start()].rstrip('/')
        if d.lower().endswith('atmosphere'):   # atmosphere/exefs_patches/<name>/
            d = d[:-len('atmosphere')].rstrip('/')
        if d not in found:
            found.append(d)
    # a root inside another root is part of it (a mod's own folders)
    return [r for r in found if not any(o != r and (o == '' or r.startswith(o + '/')) for o in found)]


def import_zip(zip_path: str | Path, folder: Path, title_id: str) -> list[str]:
    """Extract the mods of a zip into folder: each folder of the zip that is a mod becomes one (named after it, or after the zip
    when the mod is the zip's top). One mod comes in switched on, several (variants of one mod) switched off, for the player to
    pick. A mod already there by that name is replaced. Returns the names, in the archive's order."""
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path) as z:
        entries = []
        for info in z.infolist():
            p = PurePosixPath(info.filename.replace('\\', '/'))
            if p.is_absolute() or '..' in p.parts or not p.parts:
                continue
            entries.append((info, p))
        dirs = {str(p) for i, p in entries if i.is_dir()} | {str(q) for _, p in entries for q in p.parents if str(q) != '.'}
        files = {str(p) for i, p in entries if not i.is_dir()}
        roots = _roots(dirs, files, title_id)
        if not roots:
            return []
        names = []
        many = len(roots) > 1
        folder.mkdir(parents=True, exist_ok=True)
        for r in roots:
            name = _safe(PurePosixPath(r).name if r else zip_path.stem)
            for old in (folder / name, folder / ('.' + name)):
                if old.exists():
                    shutil.rmtree(old)
            dest = folder / (('.' if many else '') + name)
            prefix = r + '/' if r else ''
            for info, p in entries:
                s = str(p)
                if info.is_dir() or not s.startswith(prefix):
                    continue
                out = dest.joinpath(*PurePosixPath(s[len(prefix):]).parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(out, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
            names.append(name)
        return names


def import_folder(src: str | Path, folder: Path, title_id: str) -> list[str]:
    """Copy the mods of a folder into folder, by the same rule as import_zip."""
    src = Path(src)
    dirs, files = set(), set()
    for dirpath, dirnames, filenames in os.walk(src):
        rel = Path(dirpath).relative_to(src).as_posix()
        for d in dirnames:
            dirs.add(f'{rel}/{d}' if rel != '.' else d)
        for f in filenames:
            files.add(f'{rel}/{f}' if rel != '.' else f)
    roots = _roots(dirs, files, title_id)
    names = []
    many = len(roots) > 1
    folder.mkdir(parents=True, exist_ok=True)
    for r in roots:
        name = _safe(PurePosixPath(r).name if r else src.name)
        for old in (folder / name, folder / ('.' + name)):
            if old.exists():
                shutil.rmtree(old)
        shutil.copytree(src / r if r else src, folder / (('.' if many else '') + name))
        names.append(name)
    return names


def import_path(path: str | Path, folder: Path, title_id: str) -> list[str]:
    """A zip (import_zip), or one code patch file (.pchtxt, .ips) as a mod of its own, named after the file and switched on."""
    path = Path(path)
    if path.suffix.lower() == '.zip':
        return import_zip(path, folder, title_id)
    if path.suffix.lower() not in ('.pchtxt', '.ips'):
        return []
    name = _safe(path.stem)
    for old in (folder / name, folder / ('.' + name)):
        if old.exists():
            shutil.rmtree(old)
    (folder / name / 'exefs').mkdir(parents=True)
    shutil.copy2(path, folder / name / 'exefs' / path.name)
    return [name]


@dataclass
class Built:
    """What the last build of a game shows: its main's build ID and the code mods the engine wrote into it (engine
    patch_nso.py's <module>.mods.tsv, which the app carries: mod name to its number of patches)."""
    build_id: str | None = None
    mods: dict[str, int] = field(default_factory=dict)
    where: str = ''


def _parse_id(text: str) -> str | None:
    m = re.search(r'#\s*BUILD_ID\s+([0-9A-Fa-f]{32})', text)
    return m.group(1).lower() if m else None


def _count(texts: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for text in texts:
        for line in text.splitlines():
            if line and not line.startswith('#'):
                name = line.split('\t', 1)[0]
                out[name] = out.get(name, 0) + 1
    return out


def last_build(work_dir: str | None, ipa_path: str | None, title_id: str, shell_dir: str | None = None) -> Built:
    """The game as it was last built: the rewriter's tables in the build folder, the shell framework or the IPA (a shared IPA
    holds one framework per game, DmGame<title ID>.framework), the first that has them."""
    tid = title_id.upper()
    folders: list[Path] = []
    if work_dir and os.path.isdir(work_dir):
        folders += [p.parent for p in sorted(Path(work_dir).glob('patched_*/main.fixups.tsv'), key=lambda p: p.stat().st_mtime, reverse=True)]
    if shell_dir:
        folders.append(Path(shell_dir, f'DmGame{tid}.framework', 'dm'))
    for d in folders:
        try:
            if (d / 'main.fixups.tsv').is_file() and (b := _parse_id((d / 'main.fixups.tsv').read_text(encoding='utf-8', errors='replace')[:2048])):
                texts = [t.read_text(encoding='utf-8', errors='replace') for t in sorted(d.glob('*.mods.tsv'))]
                return Built(b, _count(texts), str(d))
        except OSError:
            pass
    if ipa_path and os.path.isfile(ipa_path):
        try:
            with zipfile.ZipFile(ipa_path) as z:
                names = [n for n in z.namelist() if n.endswith('/main.fixups.tsv')]
                own = [n for n in names if f'DmGame{tid}.framework/' in n] or (names if len(names) == 1 else [])
                for n in own:
                    if b := _parse_id(z.read(n)[:2048].decode('utf-8', errors='replace')):
                        base = n[:-len('main.fixups.tsv')]
                        texts = [z.read(x).decode('utf-8', errors='replace') for x in z.namelist()
                                 if x.startswith(base) and x.endswith('.mods.tsv') and '/' not in x[len(base):]]
                        return Built(b, _count(texts), ipa_path)
        except (OSError, zipfile.BadZipFile):
            pass
    return Built()
