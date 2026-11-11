"""How long a game's build will take on this PC, shown in the library and the build queue.

Most of a build is compiling the game's shaders for the iPhone's GPU, one Metal compile each, so the time follows the
number of shaders its profile lists (dm/games/<title ID>/shader_map.tsv): 5,318 for Luigi's Mansion 3, 27,985 for
Super Mario Odyssey, 131,427 for Pokémon Pokopia. The rate starts from a measured build (Super Mario Odyssey's first
Windows build: 81 minutes, about 0.17 s a shader before the precompiled header worked again, about 40% less per compile
since) and then follows this PC: each full build's time per shader is folded in (rate_after). A game built before
reuses its compiled shaders (Mario 1.4.1 after 1.0.0 reused 32,759 of 36,682 compiles and took about 25 minutes), so a
rebuild is a fraction of a full build.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_SEC_PER_SHADER = 0.11
REBUILD_FACTOR = 0.3
OVERHEAD_SEC = 300            # extraction, rewrite, packing: minutes whatever the shader count
LEARN_WEIGHT = 0.5            # how much one measured build moves the rate
SETTINGS_KEY = 'estimate/secPerShader'

_counts: dict[str, tuple[float, int]] = {}


def shader_count(engine: str | os.PathLike, title_id: str) -> int | None:
    """The shaders the game's profile lists, None without a registered profile (a provisional one is built blind)."""
    tid = (title_id or '').upper()
    if not engine or not re.fullmatch(r'[0-9A-F]{16}', tid):
        return None
    p = Path(engine) / 'dm' / 'games' / tid / 'shader_map.tsv'
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    cached = _counts.get(str(p))
    if cached and cached[0] == mtime:
        return cached[1]
    n = 0
    with open(p, 'rb') as f:
        for line in f:
            if line.strip() and not line.startswith(b'#'):
                n += 1
    _counts[str(p)] = (mtime, n)
    return n


def has_compiled_shaders(game) -> bool:
    """Whether an earlier build left this game's compiled shaders (its <title ID>_build/shader folder)."""
    tid = (game.title_id or '').upper()
    roots: list[Path] = []
    if getattr(game, 'output_dir', ''):
        roots.append(Path(game.output_dir))
    base = ((getattr(game, 'inputs', {}) or {}).get('base') or [''])[0]
    if base:
        p = Path(base)
        roots += [p.parent, p.parent.parent]
    for r in roots:
        d = r / f'{tid}_build' / 'shader'
        try:
            if d.is_dir() and any(d.iterdir()):
                return True
        except OSError:
            continue
    return False


def estimate_seconds(engine, game, sec_per_shader: float = DEFAULT_SEC_PER_SHADER) -> int | None:
    n = shader_count(engine, game.title_id)
    if n is None:
        return None
    work = n * sec_per_shader * (REBUILD_FACTOR if has_compiled_shaders(game) else 1.0)
    return int(OVERHEAD_SEC + work)


def rate_after(rate: float, seconds: float, shaders: int) -> float:
    """The rate once a full build of `shaders` took `seconds`: a share of the old one, a share of what was measured."""
    if shaders <= 0 or seconds <= OVERHEAD_SEC:
        return rate
    measured = (seconds - OVERHEAD_SEC) / shaders
    return (1 - LEARN_WEIGHT) * rate + LEARN_WEIGHT * measured


def format_duration(seconds: int | None, *, hours: str = '{h} h {m:02d}', minutes: str = '{m} min') -> str:
    """'≈ 1 h 20', '≈ 45 min'; '' when unknown. Rounded to 5 minutes: it is an estimate."""
    if seconds is None:
        return ''
    m = max(5, int(round(seconds / 300.0)) * 5)
    return '≈ ' + (hours.format(h=m // 60, m=m % 60) if m >= 60 else minutes.format(m=m))
