"""Knowledge inside Mantella: for the NPCs in the current conversation (from the game's file channel) it adds
  - to the system prompt: common knowledge, one identity line per NPC and "never been inside" lines (cached), and
  - to the newest message: lore lines about names the player just mentioned, within the lore budget (not cached).
Nothing is added when the game hasn't said who is talking."""
import json
import logging
import os
import re

from . import knowledge as K
from . import dragonborn as DB
from . import knows as N
from . import lore as L
from . import world_knowledge as WK

HERE = os.path.dirname(os.path.abspath(__file__))
# Mantella runs with SKSE/Plugins/MantellaSoftware as its working folder
CHANNEL_DIR = os.path.normpath(os.path.join(os.getcwd(), '..', 'StorageUtilData', 'MantellaLivingWorld'))
HUB_SETTINGS = os.path.join(os.path.dirname(HERE), 'living_world', 'settings.json')
DEFAULT_LORE_BUDGET = 150
MIN_LORE_BUDGET, MAX_LORE_BUDGET = 50, 600  # lore is sent again on every reply, so the setting is capped
JOB_WORDS = {'court': 'member of the court', 'court_wizard': 'court wizard', 'commoner': 'local', 'creature': 'being', 'caravan': 'caravan trader'}
TRAVEL = {'home': 'rarely leaves {home}', 'regional': 'travels around {hold}', 'province': 'travels all over Skyrim'}

_state = {'speakers': None, 'sent': set(), 'messages': 0, 'knows': ''}
_common = {'text': None}


def reset():
    _state.update(speakers=None, sent=set(), messages=0, knows='')


def _read(path):
    try:
        with open(path, 'rb') as f:
            raw = f.read()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:  # PapyrusUtil may write names in the game's codepage
            text = raw.decode('cp1252', errors='replace')
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# Papyrus strings are case-insensitive and the game reuses a spelling it already holds, so a key written as "name" can
# come out as "Name". Keys of the game's JsonUtil files are read without case (the Integration Hub does the same).
def _section(data, kind: str) -> dict:
    found = next((v for k, v in data.items() if str(k).lower() == kind.lower()), None) if isinstance(data, dict) else None
    return found if isinstance(found, dict) else {}


def _game(data, kinds=('int', 'float', 'string', 'stringList')) -> dict:
    """A game file's JsonUtil typed values ({"string": {"Name": ...}, ...}) as one dict with lower-case keys."""
    out = {}
    for kind in kinds:
        for k, v in _section(data, kind).items():
            out.setdefault(str(k).strip().lower(), v)
    return out


def _conversation() -> dict:
    return _game(_read(os.path.join(CHANNEL_DIR, 'conversation.json')))


def _npc(base: str) -> dict:
    return _game(_read(os.path.join(CHANNEL_DIR, 'npc', base.upper() + '.json')))


def speaker_pairs() -> list[tuple[str, dict]]:
    """(base id, Knowledge profile) of each NPC in the conversation that has a profile."""
    ids = speaker_ids()
    out = []
    for base in ids:
        if not isinstance(base, str) or not re.fullmatch(r'[0-9A-Fa-f]{1,8}', base):
            continue
        name = _npc(base).get('name')
        profile = K.profile_for(name, '', base) if isinstance(name, str) and name else None
        if profile:
            out.append((base, profile))
    return out


def speaker_profiles() -> list[dict]:
    """Knowledge profiles of the NPCs the game says are in the conversation."""
    return [profile for _, profile in speaker_pairs()]


def lore_budget() -> int:
    value = _read(HUB_SETTINGS).get('lore_budget')
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return DEFAULT_LORE_BUDGET
    return min(MAX_LORE_BUDGET, max(MIN_LORE_BUDGET, value))


# Lines of common_knowledge.txt that hold only before or only after the dragon attack on Helgen
HELGEN_QUESTS = ('MQ101', 'MQ102', 'MQ104')
_BEFORE, _AFTER = 'Before Helgen: ', 'After Helgen: '
# Lines that hold only while the civil war goes on, or only after one side won (World's CWFinale done + war_side)
WAR_END_QUEST = 'CWFinale'
_WAR = {'on': 'War on: ', 'Legion': 'War over (Legion): ', 'Stormcloaks': 'War over (Stormcloaks): '}


def before_helgen(states) -> bool:
    """True only when World says the main quest has not reached Helgen yet. Without World it has: the game opens there."""
    return isinstance(states, dict) and all(states.get(q) == 0 for q in HELGEN_QUESTS)


def war_state(states) -> str:
    # 'Legion' or 'Stormcloaks' once World says that side won the civil war, else 'on'
    if isinstance(states, dict) and states.get(WAR_END_QUEST) == 2 and states.get('war_side') in ('Legion', 'Stormcloaks'):
        return states['war_side']
    return 'on'


def common_knowledge(states=None) -> str:
    if _common['text'] is None:
        try:
            with open(os.path.join(K.data_dir(), 'common_knowledge.txt'), encoding='utf-8') as f:
                _common['text'] = f.read().strip()
        except OSError:
            _common['text'] = ''
    drop, keep = (_AFTER, _BEFORE) if before_helgen(states) else (_BEFORE, _AFTER)
    war = _WAR[war_state(states)]
    drop = (drop,) + tuple(p for p in _WAR.values() if p != war)
    lines = []
    for l in _common['text'].splitlines():
        if l.startswith(drop):
            continue
        prefix = next((p for p in (keep, war) if l.startswith(p)), '')
        lines.append(l[len(prefix):])
    return '\n'.join(lines)


def identity_text(p: dict) -> str:
    """One NPC's identity line and "never been inside" line, worked out from the profile."""
    return identity_lines([dict(p, lines=None)])


def identity_lines(profiles: list[dict]) -> str:
    """The identity lines for the speakers: shipped ready-made in profiles.json ("lines", tools/build_lines.py); worked
    out here for a profile without them."""
    lines = []
    for p in profiles:
        if isinstance(p.get('lines'), str) and p['lines'].strip():
            lines.append(p['lines'].strip())
            continue
        name, home, hold = p.get('name', '?'), p.get('home'), p.get('hold')
        job = JOB_WORDS.get(p.get('profession'), (p.get('profession') or 'local').replace('_', ' '))
        job = ('an ' if job[:1] in 'aeiou' else 'a ') + job
        travel = TRAVEL.get(p.get('travel'), '').format(home=home, hold=hold or 'Skyrim') if home or p.get('travel') == 'province' else ''
        where = ', '.join(w for w in (home, hold) if w) or 'Skyrim'
        origin = p.get('origin_province')
        line = f"Identity: {name} is {job} in {where}" + (f", from {origin}" if origin and origin != 'Skyrim' else '')
        lines.append(line + (f"; {travel}." if travel else '.'))
        never = [t['place'] for t in p.get('ties', []) if isinstance(t, dict) and t.get('place') and not t.get('inside')
                 and t['place'].lower() != (home or '').lower() and t.get('level') != 5]  # home and level 5: been there
        if never:
            lines.append(f"{name} has never been inside {', '.join(never)}.")
    return '\n'.join(lines)


def world() -> dict:
    """The World module's world.json (plain JSON), or {} without World, or while it still holds another
    character's or a later save's state: World is rewriting it after a load ("loading" 1), its player is not the one
    talking, or its day is later than today."""
    data = _read(os.path.join(CHANNEL_DIR, 'world.json'))
    if not data or data.get('loading') == 1:
        return {}
    conv = _conversation()
    player, today = conv.get('player'), conv.get('day')
    if isinstance(player, str) and player and isinstance(data.get('player'), str) and data['player'] \
            and data['player'] != player:
        return {}
    day = data.get('day')
    if isinstance(today, int) and isinstance(day, (int, float)) and not isinstance(day, bool) and int(day) > today:
        return {}
    return data


def quest_states():
    """{quest editor id: 0 not started, 1 running, 2 done} from World, or None without World. Also holds
    'war_side' (the side the player joined in the civil war) when World knows it."""
    data = world()
    states = data.get('quest_state')
    if not isinstance(states, dict):
        return None
    out = {k: v for k, v in states.items() if isinstance(v, int)}
    if data.get('war_side') in ('Legion', 'Stormcloaks'):
        out['war_side'] = data['war_side']
    return out


_resources = {'data': None}


def gather_hints(profiles) -> list[str]:
    """For speakers with a Missives job asking for an ore (their file's "job"): up to two mines they would know,
    their own hold first (data/resources.json, built from the lore by tools/build_resources.py)."""
    if _resources['data'] is None:
        _resources['data'] = _read(os.path.join(K.data_dir(), 'resources.json'))
    wanted = [p.get('name') for p in profiles]
    lines = []
    for base, profile in speaker_pairs():  # each job stays with the NPC whose file it is in
        if profile.get('name') not in wanted:
            continue
        job = _npc(base).get('job')
        job = job if isinstance(job, str) else ''
        for ore, mines in _resources['data'].items():
            if ore.lower() in job.lower():
                mines = sorted(mines, key=lambda m: m.get('hold') != profile.get('hold'))[:2]
                names = ' or '.join(f"{m['mine']} in {m['hold']}" if m.get('hold') else m['mine'] for m in mines)
                lines.append(f"{profile.get('name')} knows where {ore} is mined: {names}.")
    return lines


# Stock bios carry lines for quest stages ("If the golden claw has been returned: ..."). The NPC's own block now says
# what holds at the current stage, so those lines would contradict it. Character lines ("When flirting: ...") stay.
_STAGE_LINE = re.compile(r'^(If|Once|After|Before)\b([^\n:]*):.*$\n?', re.M)
# a condition about the story, not about the character ("If asked about her past:" stays)
_STAGE_WORDS = re.compile(r'\b(you (finish|complete|start|return|bring|found|find)|has been (returned|completed|found|done)|'
                          r'quest|after the|before the|once the)\b', re.I)
_quest_titles = {'list': None}


def _is_stage(condition: str) -> bool:
    if _quest_titles['list'] is None:
        _quest_titles['list'] = [t.lower() for t in _read(os.path.join(K.data_dir(), 'quest_ids.json')) if len(t) > 6]
    low = condition.lower()
    return bool(_STAGE_WORDS.search(condition)) or any(t in low for t in _quest_titles['list'])


def strip_stage_lines(text: str) -> str:
    return _STAGE_LINE.sub(lambda m: '' if _is_stage(m.group(2)) else m.group(0), text).rstrip()


def mode() -> str:
    """'full' (profiles and lore), 'profiles' (no lore lines) or 'off', from the Living World tab."""
    value = _read(HUB_SETTINGS).get('knowledge_mode')
    return value if value in ('full', 'profiles', 'off') else 'full'


_bio_fixes = {'list': None}


def fix_bios(text: str, names) -> str:
    """Mantella's stock bios with known mistakes fixed (data/bio_fixes.json: a wrong name, or a later quest told as
    already done), for the NPCs talking. Their own file is never changed."""
    if _bio_fixes['list'] is None:
        try:
            with open(os.path.join(K.data_dir(), 'bio_fixes.json'), encoding='utf-8') as f:
                _bio_fixes['list'] = [x for x in json.load(f) if isinstance(x, dict) and x.get('find')]
        except (OSError, ValueError):
            _bio_fixes['list'] = []
    for fix in _bio_fixes['list']:
        if fix.get('name') in names:
            text = text.replace(fix['find'], fix.get('replace') or '')
    return text


def exe_speaker_ids() -> list[str]:
    """Base ids of the NPCs Direct AI Connect is answering for (6 hex digits, upper case), set before each request;
    [] outside Mantella or with an exe that does not expose them."""
    try:
        from src import extensions as src_extensions
        ids = getattr(src_extensions.registry(), 'speaking_ids', None)
    except Exception:  # noqa: BLE001 - not inside Mantella, or an older exe
        return []
    return [i.upper() for i in ids if isinstance(i, str) and re.fullmatch(r'[0-9A-Fa-f]{1,8}', i)] if isinstance(ids, list) else []


def speaker_ids() -> list[str]:
    """The conversation's NPC base ids. The game writes conversation.json only after Mantella sent its greeting
    request, so when the file has no speakers, or not the ones the exe is answering for (left from the last talk),
    the exe's ids are used."""
    ids = _conversation().get('speakers') or []
    ids = [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []
    exe = exe_speaker_ids()
    if exe and not set(exe) <= {i.upper() for i in ids}:
        return exe
    return ids


def world_speakers() -> list[dict]:
    """Every NPC in the conversation (a profile or not), as world knowledge conditions read them."""
    out = []
    for base in speaker_ids():
        if not isinstance(base, str) or not re.fullmatch(r'[0-9A-Fa-f]{1,8}', base):
            continue
        flat = _game(_read(os.path.join(CHANNEL_DIR, 'npc', base.upper() + '.json')), ('int', 'string', 'stringList'))
        name = flat.get('name')
        profile = K.profile_for(name, '', base) if isinstance(name, str) and name else None
        view = WK.npc_view(base, flat, profile)
        if view['name']:
            out.append(view)
    return out


def write_checks(packs=None, state=None) -> bool:
    """Writes knowledge_checks.json (what the game reads when an NPC joins) for the packs in use; never raises."""
    try:
        packs = WK.load_packs() if packs is None else packs
        return WK.write_checks(CHANNEL_DIR, packs, WK.load_state() if state is None else state)
    except Exception as e:  # noqa: BLE001 - a broken pack never stops Mantella
        logging.getLogger('Mantella').warning(f"Knowledge: game checks not written ({e})")
        return False


def _world_inputs():
    """(packs, state, speakers, game data) for world knowledge; the game side's check list is refreshed on the way."""
    packs = WK.load_packs()
    if not packs:
        return [], None, [], None
    state = WK.load_state()
    write_checks(packs, state)
    player = _conversation().get('player') or ''
    game = WK.game_state(_read(os.path.join(CHANNEL_DIR, WK.CHECKED_FILE)), world(), player)
    return packs, state, world_speakers(), game


def world_block() -> str:
    """The "always" world knowledge entries for the speakers, within the World Knowledge budget."""
    try:
        packs, state, speakers, game = _world_inputs()
        if not packs or not speakers:
            return ''
        chosen = WK.select(packs, state, speakers, game, 'always', state['budget'])
        if chosen:
            logging.getLogger('Mantella').log(23, f"Knowledge: {len(chosen)} world knowledge line(s) in the system prompt")
        return WK.system_block(chosen, speakers)
    except Exception as e:  # noqa: BLE001 - optional, never break the reply
        logging.getLogger('Mantella').warning(f"Knowledge: world knowledge left out ({e})")
        return ''


def world_reply_lines(text: str, budget: int) -> tuple[list[str], int]:
    """The "relevant" entries the player's line touches, each told once per talk: (lines, tokens used)."""
    try:
        packs, state, speakers, game = _world_inputs()
        if not packs or not speakers:
            return [], 0
        chosen = WK.select(packs, state, speakers, game, 'relevant', budget, text, sent=_state['sent'])
        return WK.reply_lines(chosen), sum(WK.tokens(e['text']) + 4 for e, _ in chosen)
    except Exception as e:  # noqa: BLE001
        logging.getLogger('Mantella').warning(f"Knowledge: world knowledge left out ({e})")
        return [], 0


def _with_world(out: dict, block: str) -> dict:
    # in the 'knows' part, which the Hub's layout already places with the fixed text before the cache point
    if block:
        out['knows'] = f"{out['knows']}\n\n{block}" if out.get('knows') else block
    return out


def system_parts(parts: dict, ctx) -> dict:
    if mode() == 'off':
        return parts
    profiles = speaker_profiles()
    if not profiles:
        # the Hub leaves the Dragonborn news to Knowledge, so NPCs without a profile still get the far/rumour wording
        player = _conversation().get('player') or 'the traveller'
        line = DB.line(quest_states(), {}, player, _read(HUB_SETTINGS).get('dragonborn_secret') is True)
        block = world_block()
        if not line and not block:
            return parts
        out = dict(parts)
        if line:
            out['identity'] = line
        return _with_world(out, block)
    # Only adds parts: the Integration Hub's layout names where they go ('__order__') and the cache points.
    out = dict(parts)
    if isinstance(out.get('background'), str):
        out['background'] = fix_bios(out['background'], {p.get('name') for p in profiles})
    states = quest_states()
    out['common_knowledge'] = common_knowledge(states)
    player = _conversation().get('player') or 'the traveller'
    secret =_read(HUB_SETTINGS).get('dragonborn_secret') is True
    lines = [identity_lines(profiles)] + list(dict.fromkeys(l for l in (DB.line(states, p, player, secret) for p in profiles) if l))
    lines += gather_hints(profiles)
    out['identity'] = '\n'.join(l for l in lines if l)
    # the whole talk shares one prompt: with others there, a secret is marked as never said in front of them
    speakers = _conversation().get('speakers')
    talkers = len(speakers) if isinstance(speakers, list) else 0
    knows = [N.knows_block(p.get('name'), p.get('base_id', ''), states, speakers=max(talkers, len(profiles))) for p in profiles]
    _state['knows'] = '\n'.join(knows)
    if any(knows):
        out['knows'] = '\n\n'.join(k for k in knows if k)
        if isinstance(out.get('background'), str):
            out['background'] = strip_stage_lines(out['background'])
    return _with_world(out, world_block())


def _player_line(ctx) -> str:
    for message in reversed(ctx.get('messages') or []):
        if message.get('role') != 'user':
            continue
        content = message.get('content')
        if isinstance(content, list):
            content = ' '.join(p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text')
        return re.sub(r'\([^)]*\)', ' ', content or '').strip()
    return ''


def extra_user_text(ctx) -> str:
    profiles = speaker_profiles()
    # NPCs without a profile only matter to world knowledge, so they tell a new talk only when nobody has a profile
    names = tuple(p.get('name') for p in profiles) or tuple(s['name'] for s in world_speakers())
    count = len(ctx.get('messages') or [])
    # a new talk (other people, or a shorter thread than last time): lore may be told again
    if names != _state['speakers'] or count < _state['messages']:
        _state.update(speakers=names, sent=set(), knows='' if names != _state['speakers'] else _state['knows'])
    _state['messages'] = count
    text = _player_line(ctx)
    if not text or mode() == 'off':
        return ''
    # world knowledge the player's line touches comes first; lore gets what is left of the same budget
    lines, used = world_reply_lines(text, lore_budget())
    if not profiles or mode() != 'full':
        return '\n'.join(lines)
    budget = max(0, lore_budget() - used) // len(profiles)
    for p in profiles:
        facts = L.lookup(text, p, budget, world={'quests': world().get('quests') or {}}, sent=_state['sent'])
        # what the NPC's own block already says needs no lore line (rule: never send what the prompt has)
        facts = [f for f in facts if f.split(' is ')[0] not in _state.get('knows', '')]
        if facts:
            lines.append(f"(What {p.get('name')} knows about this: {' '.join(facts)})")
            logging.getLogger('Mantella').log(23, f"Knowledge: {len(facts)} lore line(s) for {p.get('name')}")
    return '\n'.join(lines)
