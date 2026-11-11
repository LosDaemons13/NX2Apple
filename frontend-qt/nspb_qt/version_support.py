"""Whether a game is built from a version its engine profile was brought up on, said before the build and in the IPA.

A game's profile (`dm/games/<title ID>/game.tsv`) registers the versions it was brought up on, one `build` row each
(`build  v393216  1.4.1  main=…`). A build from any other version derives a profile from it and says so only in its
log ("[RED] this shell framework uses v0 (1.0.0), which game profile … was not brought up on"). Such a game often stops
at start: Super Mario Odyssey 1.0.0 crashed in its SDK's startup on an iPhone, where 1.4.1 plays. So the launcher asks
before such a build, and marks the game's manifest in the IPA (`version_supported`, `supported_versions`) so the
iPhone asks again before Play instead of crashing without a word. Profiles that register no build row say nothing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

#: Keys this module adds to `game.manifest.json`. The shell reads them; readers ignore keys they do not know.
SUPPORTED_KEY = 'version_supported'
VERSIONS_KEY = 'supported_versions'


@dataclass(frozen=True)
class Mismatch:
    title_id: str
    have: int                     # the package version the build would use, 0 for the base game alone
    supported: tuple[str, ...]    # the registered display versions ('1.4.1',)


def _version_number(text: str) -> int | None:
    m = re.fullmatch(r'v?(\d+)', text.strip())
    return int(m.group(1)) if m else None


def registered(repo: str | Path, title_id: str) -> list[tuple[int, str]]:
    """The (package version, display version) pairs the game's profile was brought up on; [] when it registers none."""
    tid = title_id.strip().upper()
    if not repo or not re.fullmatch(r'[0-9A-F]{16}', tid):
        return []
    tsv = Path(repo) / 'dm' / 'games' / tid / 'game.tsv'
    try:
        lines = tsv.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []
    rows: list[tuple[int, str]] = []
    for line in lines:
        cells = line.split('\t')
        if cells[0] != 'build' or len(cells) < 2:
            continue
        number = _version_number(cells[1])
        if number is None:
            continue
        display = cells[2].strip() if len(cells) > 2 and cells[2].strip() and '=' not in cells[2] else cells[1].strip()
        rows.append((number, display))
    return rows


def check(repo: str | Path, title_id: str, have: int | None) -> Mismatch | None:
    """A Mismatch when the profile registers versions and `have` is none of them; None when it fits or nothing is known."""
    if have is None:
        return None
    rows = registered(repo, title_id)
    if not rows or have in {v for v, _ in rows}:
        return None
    return Mismatch(title_id=title_id.strip().upper(), have=have, supported=tuple(dict.fromkeys(d for _, d in rows)))


def annotate_manifest(framework: str | Path, repo: str | Path) -> bool | None:
    """Write whether the framework's version is supported into its `game.manifest.json`.

    Returns the verdict, or None when the profile registers no version (the keys are then removed, so an old verdict
    never outlives its profile). The file is rewritten only when the verdict changes.
    """
    path = Path(framework) / 'game.manifest.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    rows = registered(repo, str(data.get('title_id') or ''))
    have = _version_number(str(data.get('package_version') or ''))
    before = (data.get(SUPPORTED_KEY), data.get(VERSIONS_KEY))
    if not rows or have is None:
        verdict = None
        data.pop(SUPPORTED_KEY, None)
        data.pop(VERSIONS_KEY, None)
    else:
        verdict = have in {v for v, _ in rows}
        data[SUPPORTED_KEY] = verdict
        data[VERSIONS_KEY] = list(dict.fromkeys(d for _, d in rows))
    if (data.get(SUPPORTED_KEY), data.get(VERSIONS_KEY)) != before:
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
        except OSError:
            return verdict
    return verdict


def needs_mac(repo: str | Path, title_id: str) -> bool:
    """Whether the game's shaders are captured by running it (its profile has vk_capture.tsv: Super Mario Galaxy 1 and 2,
    Super Mario Sunshine): the Windows driver cannot do that and stops the build with "this game compiles its shaders at
    run time ... needs a Mac", after a minute of extraction. Said before the build instead."""
    tid = title_id.strip().upper()
    if not repo or not re.fullmatch(r'[0-9A-F]{16}', tid):
        return False
    return (Path(repo) / 'dm' / 'games' / tid / 'vk_capture.tsv').is_file()
