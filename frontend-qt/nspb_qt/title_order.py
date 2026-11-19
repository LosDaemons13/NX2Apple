"""Games in alphabetical order: the collection, the build queue and its dialog, and the games picked for the shared IPA.

The order a reader expects from the names: accents and case do not count ("Pokemon Pokopia" and "Pokémon Legends: Z-A" sit
together, "SUPER MARIO ODYSSEY" among the S), nor do ™ and ® (dumps carry them: "Pokémon™ Violet"), and numbers count as
numbers ("Mario Kart 8" before "Mario Kart 10"). The title ID breaks a tie, so two games of the same name keep one order.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar('T')

_MARKS = str.maketrans('', '', '™®©℠')
_NUMBER = re.compile(r'(\d+)')


def sort_key(name: str, title_id: str = '') -> tuple:
    """The key that puts `name` in alphabetical order (see the module)."""
    text = unicodedata.normalize('NFKD', (name or title_id).translate(_MARKS))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).casefold().strip()
    parts = tuple((0, int(p), '') if p.isdigit() else (1, 0, p) for p in _NUMBER.split(text) if p)
    return parts, (title_id or '').upper()


def alphabetical(items: Iterable[T], name: Callable[[T], str] = lambda g: g.name,
                 title_id: Callable[[T], str] = lambda g: g.title_id) -> list[T]:
    """`items` (games, rows: anything with a name and a title ID) in alphabetical order of their names."""
    return sorted(items, key=lambda g: sort_key(name(g) or '', title_id(g) or ''))
