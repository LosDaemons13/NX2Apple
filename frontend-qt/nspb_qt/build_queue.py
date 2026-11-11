"""Builds one after the other: tick several games, leave the PC on, and each is built when the one before ends.

The window owns the steps (it loads each game from the library and presses Build for it, MainWindow._queue_start_next);
this module holds the order and the outcome of each, and the rows the queue dialog shows. Builds run one at a time on
purpose: one build already takes every core and much of the memory (the shader stage above all), so two at once would
not end sooner.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field


@dataclass
class BuildQueue:
    waiting: list[str] = field(default_factory=list)            # title IDs, in build order
    current: str | None = None                                   # the queued game being built
    results: list[tuple[str, str]] = field(default_factory=list)  # (title ID, 'ok' | 'failed' | 'skipped')

    @property
    def active(self) -> bool:
        return self.current is not None or bool(self.waiting)

    def set(self, ids: Iterable[str]) -> None:
        """A new queue: the outcomes of the last one are forgotten."""
        self.waiting = []
        self.current = None
        self.results = []
        self.extend(ids)

    def extend(self, ids: Iterable[str]) -> None:
        """Add games at the end, each once (not the one being built)."""
        for tid in ids:
            key = tid.upper()
            if key != (self.current or '').upper() and key not in (w.upper() for w in self.waiting):
                self.waiting.append(tid)

    def clear(self) -> None:
        self.waiting = []
        self.current = None

    def next(self) -> str | None:
        """The next game to build, now the current one; None when the queue is empty."""
        self.current = self.waiting.pop(0) if self.waiting else None
        return self.current

    def finish_current(self, outcome: str) -> None:
        if self.current is not None:
            self.results.append((self.current, outcome))
            self.current = None

    def counts(self) -> dict[str, int]:
        out = {'ok': 0, 'failed': 0, 'skipped': 0}
        for _, outcome in self.results:
            out[outcome] = out.get(outcome, 0) + 1
        return out

    def position(self) -> tuple[int, int]:
        """(number of the current build, total of this queue), 1-based."""
        done = len(self.results)
        return done + 1, done + (1 if self.current else 0) + len(self.waiting)


@dataclass(frozen=True)
class QueueRow:
    title_id: str
    name: str
    status: str             # 'running' | 'queued' | 'missing' | 'version' | 'built' | 'new'
    checked: bool
    enabled: bool
    supported: str = ''     # for 'version': the versions the profile was brought up on


def queue_rows(games: Iterable, *, running_id: str = '', queue: BuildQueue | None = None,
               unsupported: Callable[[object], tuple[str, ...] | None] = lambda g: None) -> list[QueueRow]:
    """The dialog's rows: what is ticked at first, and what cannot be ticked.

    Ticked: games not built yet, and games already waiting. Not ticked: games already built (built again only on
    purpose) and games whose files give a version their profile was not brought up on (they would most likely crash
    at start; the player can still tick them). Not selectable: the game being built, and games whose files are gone.
    """
    waiting = {w.upper() for w in (queue.waiting if queue else [])}
    rows: list[QueueRow] = []
    for g in games:
        tid = g.title_id
        if running_id and tid.upper() == running_id.upper():
            rows.append(QueueRow(tid, g.name, 'running', False, False))
        elif tid.upper() in waiting:
            rows.append(QueueRow(tid, g.name, 'queued', True, True))
        elif not g.can_rebuild:   # its base game file or folder is gone (the keys are the window's when the game has none)
            rows.append(QueueRow(tid, g.name, 'missing', False, False))
        elif (versions := unsupported(g)) is not None:
            rows.append(QueueRow(tid, g.name, 'version', False, True, ', '.join(versions)))
        elif g.has_any_build:
            rows.append(QueueRow(tid, g.name, 'built', False, True))
        else:
            rows.append(QueueRow(tid, g.name, 'new', True, True))
    return rows
