"""World knowledge: facts bigger than one NPC that only some NPCs know, written by the player or shipped by mods.

Facts come in knowledge packs, JSON files in data/living_world/knowledge_packs/ (next to Mantella's own data folder,
so a mod ships one at SKSE/Plugins/MantellaSoftware/data/living_world/knowledge_packs/<name>.json):

    {"format": 1, "id": "riverwood_news", "name": "Riverwood news", "source": "player", "enabled": true,
     "groups": {"Riverwood folk": ["Lucan Valerius", "Camilla Valerius", "0001347B"]},
     "entries": [{"id": "e1", "text": "The mill's saw blade broke last week.", "mode": "always",
                  "conditions": "location: Riverwood or group: Riverwood folk", "enabled": true}]}

Each entry has text, conditions, a mode, an enabled flag and a source (the pack's unless the entry names its own).
Mode "always": in the system prompt of every NPC whose conditions pass. Mode "relevant": only in the reply where the
player's line touches it (keywords now; set_relevance() lets a meaning search replace that).

Conditions are written as text (or as the JSON shape parse_conditions returns): leaves joined by "and", "or", "not"
and parentheses, "and" binding tighter than "or". Quote a value that holds one of those words ("Hunters and Trappers").
    location: Riverwood       the NPC is there now, or lives there (a house or shop inside a town counts as the town)
    hold: The Rift            the NPC lives in or is now in that hold
    faction: Companions       one of the guilds and sides, or the vanilla job, the game writes into the NPC's file
                              (also guard and follower); "faction: Skyrim.esm|0x048362" any faction, checked in game
    group: Riverwood folk     a named group of the pack: NPC names or base ids
    quest: MQ104 >= 90        quest stage at least / at most (>=, <=, >, <, =); "quest: MQ104 done" / "not done"
    global: Skyrim.esm|0x39 >= 30   a global's value (==, !=, >=, <=, >, <)
No conditions: every NPC knows it.

Game data the server never sees (other factions, globals, quests) is read by the Knowledge plugin's MLWK_Checks when an
NPC joins a talk: the server lists what to read in knowledge_checks.json, the game writes knowledge_checked.json. A
condition whose data is missing counts as not met. Nothing here raises: a broken pack or entry is left out and its
problems are shown on the World Knowledge page."""
import json
import os
import re
import shutil
import threading
import time

from . import knowledge as K

PACKS_DIR = os.path.join('data', 'living_world', 'knowledge_packs')
STATE_FILE = os.path.join('data', 'living_world', 'knowledge_packs_enabled.json')  # the player's on/off choices
DELETED_DIR = os.path.join('data', 'living_world', 'knowledge_packs_deleted')
CHECKS_FILE = 'knowledge_checks.json'    # in the game channel folder: what MLWK_Checks reads in game
CHECKED_FILE = 'knowledge_checked.json'  # written by MLWK_Checks
FORMAT = 1
MODES = ('always', 'relevant')
PLAYER_SOURCE = 'player'
DEFAULT_BUDGET, MAX_BUDGET = 200, 600  # tokens of "always" entries in the system prompt
LEAVES = ('location', 'hold', 'faction', 'group', 'quest', 'global')
OPS = {'==': lambda a, b: a == b, '!=': lambda a, b: a != b, '>=': lambda a, b: a >= b, '<=': lambda a, b: a <= b,
       '>': lambda a, b: a > b, '<': lambda a, b: a < b}
_ID = re.compile(r'[^a-z0-9_]+')
_FORM = re.compile(r'^\s*([^|]+\.(?:esp|esm|esl))\s*\|\s*(?:0x)?([0-9a-f]{1,8})\s*$', re.I)
_HEX_ID = re.compile(r'^[0-9a-f]{6,8}$', re.I)
_lock = threading.Lock()


def tokens(text: str) -> int:
    return max(1, len(text) // 4)  # as the Hub counts them


def clean_id(value, fallback='pack') -> str:
    text = _ID.sub('_', str(value or '').strip().lower()).strip('_')
    return text or fallback


def form_key(value):
    """"Skyrim.esm|0x048362" as "skyrim.esm|048362" (a light plugin's FE id cut to its own 3 digits), else None."""
    m = _FORM.match(str(value or ''))
    if not m:
        return None
    number = int(m.group(2), 16)
    number = number & 0xFFF if number >> 24 == 0xFE else number & 0xFFFFFF
    return f"{m.group(1).strip().lower()}|{number:06x}"


def _base_number(value):
    try:
        return int(str(value), 16) & 0xFFFFFF
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- conditions as text

class ConditionError(ValueError):
    pass


_TOKEN = re.compile(r'\s*(?:(\()|(\))|"([^"]*)"|([^\s()"]+))')
_QUEST = re.compile(r'^(\S+)\s*(?:(==|=|>=|<=|>|<)\s*(-?\d+)|(not\s+done|done))?$', re.I)
# "quest: X <op> n" as stage bounds: (bound, shift from n)
_STAGE_BOUNDS = {'>=': (('stage_min', 0),), '<=': (('stage_max', 0),), '>': (('stage_min', 1),),
                 '<': (('stage_max', -1),), '==': (('stage_min', 0), ('stage_max', 0)),
                 '=': (('stage_min', 0), ('stage_max', 0))}
_GLOBAL = re.compile(r'^(.+?)\s*(==|!=|>=|<=|=|>|<)\s*(-?\d+(?:\.\d+)?)$')


def _tokens(text):
    out, pos = [], 0
    text = str(text or '')
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip():
                raise ConditionError(f'cannot read "{text[pos:].strip()}"')
            break
        pos = m.end()
        if m.group(1):
            out.append(('(', '('))
        elif m.group(2):
            out.append((')', ')'))
        elif m.group(3) is not None:
            out.append(('word', m.group(3)))  # quoted: never a keyword
        else:
            word = m.group(4)
            out.append((word.lower(), word) if word.lower() in ('and', 'or', 'not') else ('word', word))
    return out


def _leaf(key: str, value: str) -> dict:
    key, value = key.strip().lower(), value.strip()
    if key not in LEAVES:
        raise ConditionError(f'unknown condition "{key}" (known: {", ".join(LEAVES)})')
    if not value:
        raise ConditionError(f'"{key}:" needs a value')
    if key == 'quest':
        m = _QUEST.match(value)
        if not m:
            raise ConditionError(f'"quest: {value}": write e.g. "quest: MQ104 >= 90" or "quest: MQ104 done"')
        out = {'quest': m.group(1)}
        if m.group(2):
            stage = int(m.group(3))
            out.update({bound: stage + shift for bound, shift in _STAGE_BOUNDS[m.group(2)]})
        elif m.group(4):
            out['completed'] = not m.group(4).lower().startswith('not')
        return out
    if key == 'global':
        m = _GLOBAL.match(value)
        if not m or not form_key(m.group(1)):
            raise ConditionError(f'"global: {value}": write e.g. "global: Skyrim.esm|0x000039 >= 30"')
        number = float(m.group(3))
        return {'global': m.group(1).strip(), 'op': '==' if m.group(2) == '=' else m.group(2),
                'value': int(number) if number.is_integer() else number}
    if key == 'faction' and '|' in value and not form_key(value):
        raise ConditionError(f'"faction: {value}": a faction by form id is written e.g. "Skyrim.esm|0x048362"')
    return {key: value}


def parse_conditions(text):
    """Condition text as {'all': [...]}, {'any': [...]}, {'not': c} or one leaf; None for empty text.
    Raises ConditionError with a plain-words reason."""
    toks = _tokens(text)
    if not toks:
        return None
    pos = [0]

    def peek():
        return toks[pos[0]][0] if pos[0] < len(toks) else None

    def take():
        pos[0] += 1
        return toks[pos[0] - 1]

    def expr():
        items = [term()]
        while peek() == 'or':
            take()
            items.append(term())
        return items[0] if len(items) == 1 else {'any': items}

    def term():
        items = [factor()]
        while peek() == 'and':
            take()
            items.append(factor())
        return items[0] if len(items) == 1 else {'all': items}

    def factor():
        kind = peek()
        if kind == 'not':
            take()
            return {'not': factor()}
        if kind == '(':
            take()
            inner = expr()
            if peek() != ')':
                raise ConditionError('a "(" is never closed')
            take()
            return inner
        if kind != 'word':
            raise ConditionError(f'expected a condition, found "{toks[pos[0]][1]}"' if kind else 'the conditions end too early')
        first = take()[1]
        if ':' not in first:
            raise ConditionError(f'"{first}" is not a condition: write e.g. "hold: Whiterun"')
        key, _, rest = first.partition(':')
        words = [rest] if rest else []
        while peek() in ('word', 'not'):
            word = take()[1]
            if re.match(r'^(%s):' % '|'.join(LEAVES), word, re.I):
                raise ConditionError(f'put "and" or "or" before "{word}"')
            words.append(word)
        return _leaf(key, ' '.join(w for w in words if w))

    result = expr()
    if pos[0] < len(toks):
        raise ConditionError(f'unexpected "{toks[pos[0]][1]}"')
    return result


def _quote(value) -> str:
    text = str(value)
    if re.search(r'[()"]|\b(and|or|not)\b', text, re.I) or text != text.strip():
        return '"' + text.replace('"', "'") + '"'
    return text


def conditions_text(cond) -> str:
    """The text form of a parsed condition (parse_conditions(conditions_text(c)) == c)."""
    if not cond:
        return ''
    if 'all' in cond:
        return ' and '.join(f'({conditions_text(c)})' if 'any' in c else conditions_text(c) for c in cond['all'])
    if 'any' in cond:
        return ' or '.join(conditions_text(c) for c in cond['any'])
    if 'not' in cond:
        inner = cond['not']
        return 'not ' + (f'({conditions_text(inner)})' if 'all' in inner or 'any' in inner else conditions_text(inner))
    if 'quest' in cond:
        text = f"quest: {cond['quest']}"
        lo, hi = cond.get('stage_min'), cond.get('stage_max')
        if lo is not None and lo == hi:
            text += f' = {lo}'
        elif lo is not None and hi is not None:
            return f"{text} >= {lo} and quest: {cond['quest']} <= {hi}"
        elif lo is not None:
            text += f' >= {lo}'
        elif hi is not None:
            text += f' <= {hi}'
        if 'completed' in cond:
            text += ' done' if cond['completed'] else ' not done'
        return text
    if 'global' in cond:
        return f"global: {cond['global']} {cond.get('op', '==')} {cond.get('value')}"
    key = next(k for k in LEAVES if k in cond)
    return f'{key}: {_quote(cond[key])}'


def check_conditions(cond, path='conditions'):
    """A JSON condition (as a pack holds it) normalised, or raises ConditionError. Text is parsed first."""
    if cond is None or cond == '' or cond == [] or cond == {}:
        return None
    if isinstance(cond, str):
        return parse_conditions(cond)
    if isinstance(cond, list):
        cond = {'all': cond}
    if not isinstance(cond, dict):
        raise ConditionError(f'{path}: not a condition')
    for group in ('all', 'any'):
        if group in cond:
            items = cond[group]
            if not isinstance(items, list) or not items:
                raise ConditionError(f'{path}.{group}: needs a list of conditions')
            out = [check_conditions(c, f'{path}.{group}[{i}]') for i, c in enumerate(items)]
            if None in out:
                raise ConditionError(f'{path}.{group}: an empty condition in the list')
            return {group: out}
    if 'not' in cond:
        inner = check_conditions(cond['not'], f'{path}.not')
        if inner is None:
            raise ConditionError(f'{path}.not: needs a condition')
        return {'not': inner}
    key = next((k for k in LEAVES if k in cond), None)
    if key is None:
        raise ConditionError(f'{path}: unknown condition {sorted(cond)} (known: {", ".join(LEAVES)}, all, any, not)')
    if key == 'quest':
        out = {'quest': str(cond['quest']).strip()}
        for k in ('stage_min', 'stage_max'):
            if cond.get(k) is not None:
                if isinstance(cond[k], bool) or not isinstance(cond[k], int):
                    raise ConditionError(f'{path}.{k}: needs a whole number')
                out[k] = cond[k]
        if 'completed' in cond:
            out['completed'] = bool(cond['completed'])
        if not out['quest']:
            raise ConditionError(f'{path}: quest needs an editor id')
        return out
    if key == 'global':
        if not form_key(cond['global']):
            raise ConditionError(f'{path}: global is written "Plugin.esp|0xFormID"')
        op = '==' if cond.get('op', '==') == '=' else cond.get('op', '==')
        value = cond.get('value')
        if op not in OPS or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConditionError(f'{path}: global needs an op ({", ".join(OPS)}) and a number value')
        return {'global': str(cond['global']).strip(), 'op': op, 'value': value}
    value = str(cond[key] or '').strip()
    if not value:
        raise ConditionError(f'{path}: {key} needs a value')
    return _leaf(key, value) if key == 'faction' else {key: value}


def leaves(cond):
    if not cond:
        return
    for group in ('all', 'any'):
        if group in cond:
            for c in cond[group]:
                yield from leaves(c)
            return
    if 'not' in cond:
        yield from leaves(cond['not'])
        return
    yield cond


# ---------------------------------------------------------------- packs

def _keywords(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(',')
    return [str(k).strip() for k in value or [] if str(k).strip()] if isinstance(value, list) else []


def parse_entry(raw, index: int, pack_source: str) -> dict:
    """One entry, with 'problems' (an entry with problems is never used)."""
    problems = []
    raw = raw if isinstance(raw, dict) else {}
    text = str(raw.get('text') or '').strip()
    if not text:
        problems.append('no text')
    mode = str(raw.get('mode') or 'always').strip().lower()
    if mode not in MODES:
        problems.append(f'mode "{mode}" is not always or relevant')
    try:
        cond = check_conditions(raw.get('conditions'))
    except ConditionError as e:
        cond, problems = None, problems + [str(e)]
    return {'id': clean_id(raw.get('id'), f'e{index + 1}'), 'text': text, 'mode': mode, 'conditions': cond,
            'conditions_raw': raw.get('conditions'), 'keywords': _keywords(raw.get('keywords')),
            'enabled': raw.get('enabled', True) is not False, 'source': str(raw.get('source') or pack_source),
            'problems': problems}


def parse_pack(data, file_id: str) -> dict:
    """A pack file's data, parsed. Never raises; problems are listed on the pack and its entries."""
    problems = []
    if not isinstance(data, dict):
        data, problems = {}, ['not a knowledge pack (a JSON object with "entries")']
    pid = clean_id(data.get('id') or file_id)
    groups = {}
    raw_groups = data.get('groups') if isinstance(data.get('groups'), dict) else {}
    for name, members in raw_groups.items():
        if isinstance(members, list) and str(name).strip():
            groups[str(name).strip()] = [str(m).strip() for m in members if str(m).strip()]
    source = str(data.get('source') or data.get('name') or file_id).strip()
    entries, seen = [], set()
    raw_entries = data.get('entries') if isinstance(data.get('entries'), list) else []
    if 'entries' in data and not isinstance(data.get('entries'), list):
        problems.append('"entries" is not a list')
    for i, raw in enumerate(raw_entries):
        entry = parse_entry(raw, i, source)
        while entry['id'] in seen:
            entry['id'] += '_2'
        seen.add(entry['id'])
        entries.append(entry)
    if isinstance(data.get('format'), int) and data['format'] > FORMAT:
        problems.append(f'made for a newer Knowledge (format {data["format"]}); some parts may be ignored')
    return {'id': pid, 'name': str(data.get('name') or pid).strip(), 'source': source,
            'author': str(data.get('author') or ''), 'version': str(data.get('version') or ''),
            'description': str(data.get('description') or ''), 'enabled': data.get('enabled', True) is not False,
            'groups': groups, 'entries': entries, 'problems': problems}


def pack_data(pack: dict) -> dict:
    """A parsed pack back to its file form."""
    def entry(e):
        out = {'id': e['id'], 'text': e['text'], 'mode': e['mode'],
               'conditions': conditions_text(e['conditions']) if e['conditions'] else '', 'enabled': e['enabled']}
        if e.get('keywords'):
            out['keywords'] = list(e['keywords'])
        if e.get('source') and e['source'] != pack['source']:
            out['source'] = e['source']
        return out
    data = {'format': FORMAT, 'id': pack['id'], 'name': pack['name'], 'source': pack['source']}
    for key in ('author', 'version', 'description'):
        if pack.get(key):
            data[key] = pack[key]
    data.update(enabled=pack['enabled'], groups={k: list(v) for k, v in pack['groups'].items()},
                entries=[entry(e) for e in pack['entries']])
    return data


def editable(pack: dict) -> bool:
    """Packs the player wrote are edited here; a mod's pack only has its pack and entries turned on and off."""
    return pack.get('source') == PLAYER_SOURCE


_cache = {'sig': None, 'packs': []}


def _read_json(path):
    try:
        with open(path, 'rb') as f:
            raw = f.read()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp1252', errors='replace')
        return json.loads(text)
    except (OSError, ValueError, RecursionError):
        return None


def load_packs(folder=None) -> list[dict]:
    """Every pack in the folder, by file name; re-read only when a file changed."""
    folder = folder or PACKS_DIR
    try:
        names = sorted(f for f in os.listdir(folder) if f.lower().endswith('.json'))
        stats = [os.stat(os.path.join(folder, n)) for n in names]
        sig = (folder, tuple((n, st.st_mtime_ns, st.st_size) for n, st in zip(names, stats)))
    except OSError:
        return []
    with _lock:
        if _cache['sig'] == sig:
            return _cache['packs']
    packs, ids = [], set()
    for name in names:
        pack = parse_pack(_read_json(os.path.join(folder, name)), os.path.splitext(name)[0])
        pack['file'] = name
        if pack['id'] in ids:
            pack['problems'].append(f'another pack already has the id "{pack["id"]}"; this one is not used')
        ids.add(pack['id'])
        packs.append(pack)
    with _lock:
        _cache.update(sig=sig, packs=packs)
    return packs


def load_state(path=None) -> dict:
    data = _read_json(path or STATE_FILE)
    data = data if isinstance(data, dict) else {}
    budget = data.get('budget')
    return {'packs': dict(data['packs']) if isinstance(data.get('packs'), dict) else {},
            'entries': dict(data['entries']) if isinstance(data.get('entries'), dict) else {},
            'budget': min(MAX_BUDGET, budget) if isinstance(budget, int) and not isinstance(budget, bool) and budget >= 0
            else DEFAULT_BUDGET}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    temp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(temp, path)


def save_state(state: dict, path=None) -> None:
    _write_json(path or STATE_FILE, state)


def pack_on(pack, state) -> bool:
    value = state['packs'].get(pack['id'])
    return pack['enabled'] if not isinstance(value, bool) else value


def entry_on(pack, entry, state) -> bool:
    value = state['entries'].get(f"{pack['id']}/{entry['id']}")
    return entry['enabled'] if not isinstance(value, bool) else value


def active_entries(packs, state):
    """(pack, entry) for every usable entry: pack and entry on, no problems, pack id not taken twice."""
    for pack in packs:
        if any('is not used' in p for p in pack['problems']) or not pack_on(pack, state):
            continue
        for entry in pack['entries']:
            if not entry['problems'] and entry_on(pack, entry, state):
                yield pack, entry


def all_groups(packs, state) -> dict:
    """Named groups of the packs in use: {name lower: {pack id: set of member names lower / base numbers}}."""
    out = {}
    for pack in packs:
        if not pack_on(pack, state):
            continue
        for name, members in pack['groups'].items():
            ids = {_base_number(m) for m in members if _HEX_ID.match(m)}
            names = {m.lower() for m in members if not _HEX_ID.match(m)}
            out.setdefault(name.lower(), {})[pack['id']] = (names, ids)
    return out


# ---------------------------------------------------------------- game data

def game_checks(packs, state) -> dict:
    """What the game side has to read for the entries in use: quests, globals and factions by form id."""
    quests, globals_, factions = set(), set(), set()
    for _, entry in active_entries(packs, state):
        for leaf in leaves(entry['conditions']):
            if 'quest' in leaf:
                quests.add(leaf['quest'])
            elif 'global' in leaf:
                globals_.add(form_key(leaf['global']))
            elif 'faction' in leaf and form_key(leaf['faction']):
                factions.add(form_key(leaf['faction']))
    split = lambda keys: ([k.split('|')[0] for k in keys], [int(k.split('|')[1], 16) for k in keys])
    gk, fk = sorted(globals_), sorted(factions)
    (gp, gi), (fp, fi) = split(gk), split(fk)
    return {'stringList': {'quests': sorted(quests), 'global_keys': gk, 'global_plugins': gp,
                           'faction_keys': fk, 'faction_plugins': fp},
            'intList': {'global_ids': gi, 'faction_ids': fi}}


def write_checks(channel_dir: str, packs, state) -> bool:
    """Writes knowledge_checks.json for the game side when it changed; True when written."""
    data = game_checks(packs, state)
    path = os.path.join(channel_dir, CHECKS_FILE)
    if _read_json(path) == data:
        return False
    if not os.path.isdir(channel_dir):
        return False  # no game data folder: the game side has never run here
    _write_json(path, data)
    return True


def _flatten(data) -> dict:
    flat = {}
    if isinstance(data, dict):
        for kind in ('int', 'float', 'string', 'stringList', 'intList'):
            if isinstance(data.get(kind), dict):
                flat.update({str(k).lower(): v for k, v in data[kind].items()})
    return flat


def game_state(checked, world=None, player: str = '') -> dict:
    """What the conditions read from the game: {'stages', 'done', 'globals', 'factions'}. checked: MLWK_Checks'
    knowledge_checked.json; world: World's world.json ('quests' stages, 'quest_state' 2 = done), used for quests the
    game side has not read. A checked file of another character is ignored."""
    flat = _flatten(checked)
    if player and isinstance(flat.get('player'), str) and flat['player'] and flat['player'] != player:
        flat = {}
    world = world if isinstance(world, dict) else {}
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    stages = {str(k).lower(): int(v) for k, v in (world.get('quests') or {}).items() if num(v)} \
        if isinstance(world.get('quests'), dict) else {}
    done = {str(k).lower(): v == 2 for k, v in (world.get('quest_state') or {}).items() if num(v)} \
        if isinstance(world.get('quest_state'), dict) else {}
    globals_, factions = {}, {}
    for key, value in flat.items():
        kind, _, name = key.partition(':')
        if kind == 'stage' and num(value):
            stages[name] = int(value)
        elif kind == 'done' and num(value):
            done[name] = bool(value)
        elif kind == 'global' and num(value):
            globals_[name] = value
        elif kind == 'factions' and isinstance(value, list):
            factions[_base_number(name)] = {str(v).lower() for v in value}
    return {'stages': stages, 'done': done, 'globals': globals_, 'factions': factions}


def npc_view(base_id: str, npc: dict, profile=None) -> dict:
    """What the conditions read about one NPC: the game's npc file (flattened) and their Knowledge profile, if any."""
    npc = npc if isinstance(npc, dict) else {}
    profile = profile if isinstance(profile, dict) else {}
    text = lambda v: v.strip() if isinstance(v, str) else ''
    groups = npc.get('groups') if isinstance(npc.get('groups'), list) else []
    return {'name': text(npc.get('name')) or text(profile.get('name')), 'base': _base_number(base_id),
            'location': text(npc.get('location')), 'home': text(profile.get('home')),
            'holds': [text(npc.get('hold')), text(npc.get('here_hold')), text(profile.get('hold'))],
            'groups': {text(g).lower() for g in groups if text(g)}, 'work': text(npc.get('work')).lower(),
            'guard': npc.get('guard') == 1, 'follower': npc.get('follower') == 1}


def _norm_hold(name):
    return K.norm_hold(name) or (name.strip().lower() if isinstance(name, str) and name.strip() else None)


def passes(cond, npc: dict, game: dict, groups: dict, pack_id: str = '') -> bool:
    """True when this NPC meets the condition. Missing game data: not met, also under a "not" (a leaf the game has not
    written yet is unknown, and "not unknown" is unknown too), so a fact meant to be hidden from someone never reaches
    them before the game has checked them. Never raises."""
    try:
        return _passes(cond, npc, game, groups, pack_id) is True
    except Exception:  # noqa: BLE001 - a bad condition never breaks a reply
        return False


def _passes(cond, npc, game, groups, pack_id):
    """True, False, or None when the game data the condition needs is missing."""
    if not cond:
        return True
    if 'all' in cond:
        results = [_passes(c, npc, game, groups, pack_id) for c in cond['all']]
        return False if False in results else None if None in results else True
    if 'any' in cond:
        results = [_passes(c, npc, game, groups, pack_id) for c in cond['any']]
        return True if True in results else None if None in results else False
    if 'not' in cond:
        result = _passes(cond['not'], npc, game, groups, pack_id)
        return None if result is None else not result
    key = next((k for k in LEAVES if k in cond), None)
    return _LEAF_CHECKS[key](cond, npc, game, groups, pack_id) if key else False


def _location_ok(cond, npc, game, groups, pack_id):
    want = cond['location'].lower()
    here = [npc['location'], npc['home']]
    towns = [K.resolve_place(p).get('town') for p in here if p]
    return any(isinstance(p, str) and p.lower() == want for p in here + towns)


def _hold_ok(cond, npc, game, groups, pack_id):
    want = _norm_hold(cond['hold'])
    mine = list(npc['holds']) + [K.resolve_place(p).get('hold') for p in (npc['location'], npc['home']) if p]
    return bool(want) and any(_norm_hold(h) == want for h in mine if h)


def _faction_ok(cond, npc, game, groups, pack_id):
    key = form_key(cond['faction'])
    if key:
        checked = game['factions'].get(npc['base'])
        return None if checked is None else key in checked
    want = cond['faction'].strip().lower()
    return want in npc['groups'] or want == npc['work'] or (want == 'guard' and npc['guard']) \
        or (want == 'follower' and npc['follower'])


def _group_ok(cond, npc, game, groups, pack_id):
    found = groups.get(cond['group'].strip().lower(), {})
    # the pack's own group first; a group of that name in another pack in use also counts
    sets = [found[pack_id]] if pack_id in found else list(found.values())
    return any(npc['name'].lower() in names or (npc['base'] is not None and npc['base'] in ids) for names, ids in sets)


def _quest_ok(cond, npc, game, groups, pack_id):
    quest = cond['quest'].lower()
    if 'completed' in cond:
        done = game['done'].get(quest, None if quest not in game['stages'] else False)
        if done is None:
            return None
        if done != cond['completed']:
            return False
    if 'stage_min' in cond or 'stage_max' in cond:
        stage = game['stages'].get(quest)
        if stage is None:
            return None
        return cond.get('stage_min', stage) <= stage <= cond.get('stage_max', stage)
    return 'completed' in cond


def _global_ok(cond, npc, game, groups, pack_id):
    value = game['globals'].get(form_key(cond['global']))
    return None if value is None else OPS[cond['op']](value, cond['value'])


# one check per leaf kind; a leaf holding two keys is read by the first in LEAVES order, as the if chain did
_LEAF_CHECKS = {'location': _location_ok, 'hold': _hold_ok, 'faction': _faction_ok, 'group': _group_ok,
                'quest': _quest_ok, 'global': _global_ok}


# ---------------------------------------------------------------- choosing what goes into a prompt

_WORD = re.compile(r"[A-Za-z][\w'-]*")
_STOP = {'the', 'this', 'that', 'there', 'they', 'their', 'when', 'what', 'with', 'from', 'have', 'been', 'into', 'some'}


def entry_keywords(entry) -> list[str]:
    """The entry's keywords, or the names in its text (capitalised words not starting a sentence) when it has none."""
    if entry.get('keywords'):
        return entry['keywords']
    out = []
    for sentence in re.split(r'(?<=[.!?])\s+', entry.get('text', '')):
        for word in _WORD.findall(sentence)[1:]:
            if word[0].isupper() and len(word) >= 4 and word.lower() not in _STOP and word not in out:
                out.append(word)
    return out


def keyword_relevance(text: str, entries: list[dict]) -> list[dict]:
    """The entries whose keywords appear in the player's line (whole words, any case)."""
    low = (text or '').lower()
    return [e for e in entries
            if any(re.search(r'(?<!\w)' + re.escape(k.lower()) + r'(?!\w)', low) for k in entry_keywords(e))]


_relevance = {'fn': keyword_relevance}


def set_relevance(fn=None) -> None:
    """Replace how "relevant" entries are matched: fn(player_line, entries) -> the entries that fit, best first (each
    entry has 'text' and 'keywords'). None goes back to keyword matching. A failing fn falls back to keywords."""
    _relevance['fn'] = fn if callable(fn) else keyword_relevance


def relevant(text: str, entries: list[dict]) -> list[dict]:
    if not text or not entries:
        return []
    try:
        found = _relevance['fn'](text, entries)
        ids = {id(e) for e in entries}
        return [e for e in found if id(e) in ids]
    except Exception:  # noqa: BLE001
        return keyword_relevance(text, entries)


def _who_knows(pack, entry, speakers, game, groups):
    return [s['name'] for s in speakers if s['name'] and passes(entry['conditions'], s, game, groups, pack['id'])]


def select(packs, state, speakers, game, mode: str, budget: int, text: str = '', sent=None):
    """[(entry, names who know it)] for this talk within budget tokens, in pack and entry order (relevant: best match
    first). sent: keys already given this talk; updated in place (relevant entries are told once per talk)."""
    groups = all_groups(packs, state)
    pairs = [(p, e) for p, e in active_entries(packs, state) if e['mode'] == mode
             and (sent is None or f"wk:{p['id']}/{e['id']}" not in sent)]
    if mode == 'relevant':
        order = relevant(text, [e for _, e in pairs])
        by_id = {id(e): (p, e) for p, e in pairs}
        pairs = [by_id[id(e)] for e in order]
    out, used = [], 0
    for pack, entry in pairs:
        names = _who_knows(pack, entry, speakers, game, groups)
        if not names:
            continue
        cost = tokens(entry['text']) + 4
        if used + cost > budget:
            continue
        used += cost
        out.append((entry, names))
        if sent is not None:
            sent.add(f"wk:{pack['id']}/{entry['id']}")
    return out


def system_block(chosen, speakers) -> str:
    """The "always" entries for the system prompt."""
    if not chosen:
        return ''
    everyone = [s['name'] for s in speakers if s['name']]
    if len(everyone) <= 1:
        head = f"What {everyone[0] if everyone else 'this person'} also knows about the wider world (true, and nothing beyond it):"
        return head + '\n' + '\n'.join(f"- {e['text']}" for e, _ in chosen)
    head = "What people here know about the wider world (true; only the people named know a line):"
    lines = [f"- {e['text']}" if len(names) == len(everyone) else f"- ({', '.join(names)}) {e['text']}" for e, names in chosen]
    return head + '\n' + '\n'.join(lines)


def reply_lines(chosen) -> list[str]:
    """The "relevant" entries for the newest message."""
    return [f"(What {' and '.join(names)} {'knows' if len(names) == 1 else 'know'} about this: {e['text']})" for e, names in chosen]


# ---------------------------------------------------------------- changes from the World Knowledge page

def find_pack(packs, pack_id):
    return next((p for p in packs if p['id'] == pack_id), None)


def save_pack(pack: dict, folder=None) -> str:
    folder = folder or PACKS_DIR
    path = os.path.join(folder, pack.get('file') or f"{pack['id']}.json")
    _write_json(path, pack_data(pack))
    return path


def _free_pack_id(base: str, folder: str) -> str:
    """base, or base_2, base_3, ...: the first id that no pack in the folder has and no file there is named after."""
    taken = {p['id'] for p in load_packs(folder)}
    pid, n = base, 2
    while pid in taken or os.path.exists(os.path.join(folder, pid + '.json')):
        pid, n = f'{base}_{n}', n + 1
    return pid


def new_pack(name: str, folder=None) -> dict:
    """An empty pack of the player's, with an id from its name that no pack has yet."""
    folder = folder or PACKS_DIR
    pid = _free_pack_id(clean_id(name, 'my_knowledge'), folder)
    pack = parse_pack({'id': pid, 'name': str(name or '').strip() or 'My knowledge', 'source': PLAYER_SOURCE,
                       'entries': []}, pid)
    pack['file'] = pid + '.json'
    save_pack(pack, folder)
    return pack


def save_entry(pack: dict, entry_id, text, mode, keywords, conditions, enabled, folder=None) -> tuple[str | None, list[str]]:
    """Adds (entry_id None) or replaces an entry of a player's pack. (entry id, problems); nothing saved on problems."""
    if not editable(pack):
        return None, ["this pack comes from a mod: only turning it and its entries on and off is kept"]
    entry = parse_entry({'id': entry_id or f"e{int(time.time() * 1000) % 10 ** 9}", 'text': text, 'mode': mode,
                         'keywords': keywords, 'conditions': conditions, 'enabled': bool(enabled)}, 0, pack['source'])
    if entry['problems']:
        return None, entry['problems']
    entries = list(pack['entries'])
    at = next((i for i, e in enumerate(entries) if e['id'] == entry_id), None)
    if at is None:
        while any(e['id'] == entry['id'] for e in entries):
            entry['id'] += '_2'
        entries.append(entry)
    else:
        entry['source'] = entries[at].get('source') or entry['source']
        entries[at] = entry
    save_pack(dict(pack, entries=entries), folder)
    return entry['id'], []


def delete_entry(pack: dict, entry_id, folder=None) -> bool:
    if not editable(pack) or not any(e['id'] == entry_id for e in pack['entries']):
        return False
    save_pack(dict(pack, entries=[e for e in pack['entries'] if e['id'] != entry_id]), folder)
    return True


def groups_text(groups: dict) -> str:
    return '\n'.join(f"{name}: {', '.join(members)}" for name, members in groups.items())


def parse_groups(text: str) -> dict:
    """"Group name: Name, Name, 0001347B" per line."""
    out = {}
    for line in str(text or '').splitlines():
        name, sep, members = line.partition(':')
        if sep and name.strip():
            out[name.strip()] = [m.strip() for m in members.split(',') if m.strip()]
    return out


def save_groups(pack: dict, text: str, folder=None) -> bool:
    if not editable(pack):
        return False
    save_pack(dict(pack, groups=parse_groups(text)), folder)
    return True


def set_pack_on(pack: dict, on: bool, state_path=None) -> None:
    state = load_state(state_path)
    state['packs'][pack['id']] = bool(on)
    save_state(state, state_path)


def set_entry_on(pack: dict, entry_id: str, on: bool, state_path=None) -> None:
    state = load_state(state_path)
    state['entries'][f"{pack['id']}/{entry_id}"] = bool(on)
    save_state(state, state_path)


def set_budget(value, state_path=None) -> int:
    state = load_state(state_path)
    try:
        state['budget'] = max(0, min(MAX_BUDGET, int(value)))
    except (TypeError, ValueError):
        state['budget'] = DEFAULT_BUDGET
    save_state(state, state_path)
    return state['budget']


def export_pack(pack: dict, out_dir: str, state_path=None) -> str:
    """The pack as one JSON file, with the player's on/off choices written into it."""
    state = load_state(state_path)
    data = pack_data(pack)
    data['enabled'] = pack_on(pack, state)
    for e, raw in zip(pack['entries'], data['entries']):
        raw['enabled'] = entry_on(pack, e, state)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{pack['id']}-{time.strftime('%Y%m%d-%H%M%S')}.json")
    _write_json(path, data)
    return path


def import_pack(path: str, folder=None) -> tuple[dict | None, str]:
    """Copies a pack file into the packs folder under an id no pack has yet. (pack, message)."""
    folder = folder or PACKS_DIR
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get('entries'), list):
        return None, 'Not a knowledge pack: a JSON file with an "entries" list.'
    pack = parse_pack(data, os.path.splitext(os.path.basename(path))[0])
    pack['id'] = _free_pack_id(pack['id'], folder)
    pack['file'] = pack['id'] + '.json'
    os.makedirs(folder, exist_ok=True)
    out = dict(data, id=pack['id'])
    _write_json(os.path.join(folder, pack['file']), out)
    bad = sum(1 for e in pack['entries'] if e['problems'])
    note = f" {bad} entr{'y has' if bad == 1 else 'ies have'} problems and will not be used." if bad else ''
    return pack, f"Imported \"{pack['name']}\" ({len(pack['entries'])} entries) as {pack['file']}.{note}"


def delete_pack(pack: dict, folder=None, deleted_dir=None) -> str | None:
    """Moves a player's pack file to the deleted folder (it can be put back by hand); the path, or None."""
    if not editable(pack):
        return None
    folder, deleted_dir = folder or PACKS_DIR, deleted_dir or DELETED_DIR
    os.makedirs(deleted_dir, exist_ok=True)
    target = os.path.join(deleted_dir, f"{os.path.splitext(pack['file'])[0]}-{time.strftime('%Y%m%d-%H%M%S')}.json")
    shutil.move(os.path.join(folder, pack['file']), target)
    return target
