"""The amiibo the in-game menu offers (patch 0127, virtual amiibo; ios/Launcher.m's Amiibo menu).

An amiibo is its 8-byte ID, which is all a game reads to know the figure: the menu places one on the host's NFC reader
by its ID and name, with no dump of a real figure and no key. The list is AmiiboAPI's (N3evin/AmiiboAPI, MIT; archived
2025-12-08), kept compact in `ios/amiibo.json`: each amiibo's ID and name, the series names, and for each Switch and
Switch 2 game its title IDs and what each amiibo does there (an index into a table of the texts).

Each game's build writes the list for that game into its `dm/amiibo.tsv` (`write_game_list`): one amiibo a line,
`<ID>\t<name>\t<series>\t<what it does in this game, or nothing>`, after `#` lines that name the source and its
licence. The menu shows the amiibo this game uses first, then every amiibo by series.

AmiiboAPI is in English. `ios/amiibo_i18n.json`, kept by hand so that a new AmiiboAPI list does not lose it, has another
language's series, the editions and outfits after a name's " - ", the names that differ (Isabelle is Marie in French)
and the uses. Each such language gets `dm/amiibo.<code>.tsv` (`write_game_lists`), and the menu reads the one of the
iPhone's language. What a language leaves out stays English.

Regenerate the JSON from AmiiboAPI's two files:
    python -m nspb_qt.win.amiibo_db <amiibo.json> <games_info.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent / 'ios' / 'amiibo.json'
I18N = Path(__file__).resolve().parent / 'ios' / 'amiibo_i18n.json'

SOURCE = 'AmiiboAPI (https://github.com/N3evin/AmiiboAPI), database/amiibo.json and games_info.json, MIT licence, Copyright (c) 2019 N3evin'


def generate(amiibo: dict, games_info: dict, licence: str = '') -> dict:
    """The compact database from AmiiboAPI's amiibo.json and games_info.json."""
    series = {k.lower()[2:].zfill(2): v for k, v in amiibo.get('amiibo_series', {}).items()}
    figures = sorted((k.lower()[2:], v['name']) for k, v in amiibo['amiibos'].items())
    games: dict[str, dict] = {}
    for aid, platforms in games_info.get('amiibos', {}).items():
        for game in platforms.get('gamesSwitch', []) + platforms.get('gamesSwitch2', []):
            uses = '; '.join(dict.fromkeys(u['Usage'].strip() for u in game.get('amiiboUsage', []) if u.get('Usage')))
            entry = games.setdefault(game['gameName'], {'ids': set(), 'uses': {}})
            entry['ids'].update(t.upper() for t in game.get('gameID', []))
            if uses:
                old = entry['uses'].get(aid.lower()[2:])
                entry['uses'][aid.lower()[2:]] = uses if not old or uses in old else f'{old}; {uses}'
    # A text that many amiibo share (each Animal Crossing card invites its villager) is kept once: uses give its index in texts
    texts = sorted({u for g in games.values() for u in g['uses'].values()})
    index = {t: i for i, t in enumerate(texts)}
    return {
        'source': SOURCE,
        'licence': licence,
        'series': dict(sorted(series.items())),
        'amiibo': [list(f) for f in figures],
        'texts': texts,
        'games': [{'name': n, 'ids': sorted(g['ids']), 'uses': {a: index[u] for a, u in sorted(g['uses'].items())}}
                  for n, g in sorted(games.items()) if g['ids']],
    }


def load(path: Path = DB) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def translations(path: Path | None = None) -> dict:
    """{language code: {series, suffixes, names, uses, separator}} from amiibo_i18n.json; {} without the file."""
    try:
        return json.loads((path or I18N).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _translator(tr: dict):
    """(name, series, use) in tr's language, each left as it is where tr has nothing for it."""
    names, suffixes, series, uses = (tr.get(k, {}) for k in ('names', 'suffixes', 'series', 'uses'))

    def name(n: str) -> str:
        if n in names:
            return names[n]
        base, sep, rest = n.partition(' - ')
        return names.get(base, base) + (sep + suffixes.get(rest, rest) if sep else '')

    def use(u: str) -> str:
        return tr.get('separator', '; ').join(uses.get(part, part) for part in u.split('; ')) if u else u

    return name, (lambda s: series.get(s, s)), use


def game_list(title_id: str, db: dict | None = None, tr: dict | None = None) -> str:
    """The menu's list for one game: every amiibo, with what it does in this game when the database says.
    tr: one language's translations (translations()[code]); None for English."""
    db = db or load()
    name_of, series_of, use_of = _translator(tr or {})
    tid = title_id.upper()
    uses: dict[str, str] = {}
    for game in db['games']:
        if tid in game['ids']:
            for aid, i in game['uses'].items():
                use = db['texts'][i]
                uses[aid] = use if aid not in uses or use in uses[aid] else f'{uses[aid]}; {use}'
    clean = lambda s: ' '.join(str(s).split())   # noqa: E731 (one line a row, no tab inside a field)
    head = [f'# The amiibo the in-game menu offers, for title {tid}: ID, name, series, what it does in this game',
            f'# From {db["source"]}']
    rows = [f'{aid}\t{clean(name_of(name))}\t{clean(series_of(db["series"].get(aid[12:14], "Other")))}\t{clean(use_of(uses.get(aid, "")))}'
            for aid, name in db['amiibo']]
    return '\n'.join(head + rows) + '\n'


def write_game_list(title_id: str, out: Path, db: dict | None = None, tr: dict | None = None) -> int:
    """Write the game's list; the number of amiibo the database says this game uses."""
    text = game_list(title_id, db, tr)
    out.write_text(text, encoding='utf-8', newline='\n')
    return sum(1 for line in text.splitlines() if not line.startswith('#') and line.split('\t')[3])


def write_game_lists(title_id: str, folder: Path, db: dict | None = None, langs: dict | None = None) -> int:
    """The game's list in English (amiibo.tsv) and in each language of amiibo_i18n.json (amiibo.<code>.tsv) into
    folder; the number of amiibo this game uses."""
    db = db or load()
    langs = translations() if langs is None else langs
    used = write_game_list(title_id, folder / 'amiibo.tsv', db)
    for code, tr in sorted(langs.items()):
        write_game_list(title_id, folder / f'amiibo.{code}.tsv', db, tr)
    return used


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    amiibo = json.loads(Path(argv[0]).read_text(encoding='utf-8'))
    games_info = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
    licence = Path(argv[2]).read_text(encoding='utf-8') if len(argv) == 3 else ''
    db = generate(amiibo, games_info, licence)
    DB.write_text(json.dumps(db, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8', newline='\n')
    print(f'{DB}: {len(db["amiibo"])} amiibo, {len(db["games"])} games')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
