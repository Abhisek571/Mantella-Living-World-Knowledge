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

HERE = os.path.dirname(os.path.abspath(__file__))
# Mantella runs with SKSE/Plugins/MantellaSoftware as its working folder
CHANNEL_DIR = os.path.normpath(os.path.join(os.getcwd(), '..', 'StorageUtilData', 'MantellaLivingWorld'))
HUB_SETTINGS = os.path.join(os.path.dirname(HERE), 'living_world', 'settings.json')
DEFAULT_LORE_BUDGET = 150
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


def speaker_pairs() -> list[tuple[str, dict]]:
    """(base id, Knowledge profile) of each NPC the game says is in the conversation and that has a profile."""
    ids = (_read(os.path.join(CHANNEL_DIR, 'conversation.json')).get('stringList') or {}).get('speakers') or []
    out = []
    for base in ids:
        if not isinstance(base, str) or not re.fullmatch(r'[0-9A-Fa-f]{1,8}', base):
            continue
        name = (_read(os.path.join(CHANNEL_DIR, 'npc', base.upper() + '.json')).get('string') or {}).get('name')
        profile = K.profile_for(name, '', base) if isinstance(name, str) and name else None
        if profile:
            out.append((base, profile))
    return out


def speaker_profiles() -> list[dict]:
    """Knowledge profiles of the NPCs the game says are in the conversation."""
    return [profile for _, profile in speaker_pairs()]


def lore_budget() -> int:
    value = _read(HUB_SETTINGS).get('lore_budget')
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else DEFAULT_LORE_BUDGET


def common_knowledge() -> str:
    if _common['text'] is None:
        try:
            with open(os.path.join(K.data_dir(), 'common_knowledge.txt'), encoding='utf-8') as f:
                _common['text'] = f.read().strip()
        except OSError:
            _common['text'] = ''
    return _common['text']


def identity_lines(profiles: list[dict]) -> str:
    lines = []
    for p in profiles:
        name, home, hold = p.get('name', '?'), p.get('home') or 'no fixed home', p.get('hold') or 'Skyrim'
        job = p.get('profession') or 'local'
        travel = TRAVEL.get(p.get('travel'), '').format(home=home, hold=hold)
        origin = p.get('origin_province')
        line = f"Identity: {name} is a {job} in {home}, {hold}" + (f", from {origin}" if origin and origin != 'Skyrim' else '')
        lines.append(line + (f"; {travel}." if travel else '.'))
        never = [t['place'] for t in p.get('ties', []) if isinstance(t, dict) and t.get('place') and not t.get('inside')]
        if never:
            lines.append(f"{name} has never been inside {', '.join(never)}.")
    return '\n'.join(lines)


def world() -> dict:
    """The World module's world.json (plain JSON), or {} without World."""
    return _read(os.path.join(CHANNEL_DIR, 'world.json'))


def quest_states():
    """{quest editor id: 0 not started, 1 running, 2 done} from World, or None without World."""
    states = world().get('quest_state')
    return {k: v for k, v in states.items() if isinstance(v, int)} if isinstance(states, dict) else None


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
        job = (_read(os.path.join(CHANNEL_DIR, 'npc', base.upper() + '.json')).get('string') or {}).get('job')
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


def system_parts(parts: dict, ctx) -> dict:
    if mode() == 'off':
        return parts
    profiles = speaker_profiles()
    if not profiles:
        return parts
    # Only adds parts: the Integration Hub's layout names where they go ('__order__') and the cache points.
    out = dict(parts)
    out['common_knowledge'] = common_knowledge()
    states = quest_states()
    player = (_read(os.path.join(CHANNEL_DIR, 'conversation.json')).get('string') or {}).get('player') or 'the traveller'
    secret = _read(HUB_SETTINGS).get('dragonborn_secret') is True
    lines = [identity_lines(profiles)] + list(dict.fromkeys(l for l in (DB.line(states, p, player, secret) for p in profiles) if l))
    lines += gather_hints(profiles)
    out['identity'] = '\n'.join(l for l in lines if l)
    knows = [N.knows_block(p.get('name'), p.get('base_id', ''), states) for p in profiles]
    _state['knows'] = '\n'.join(knows)
    if any(knows):
        out['knows'] = '\n\n'.join(k for k in knows if k)
        if isinstance(out.get('background'), str):
            out['background'] = strip_stage_lines(out['background'])
    return out


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
    names = tuple(p.get('name') for p in profiles)
    count = len(ctx.get('messages') or [])
    # a new talk (other people, or a shorter thread than last time): lore may be told again
    if names != _state['speakers'] or count < _state['messages']:
        _state.update(speakers=names, sent=set(), knows='' if names != _state['speakers'] else _state['knows'])
    _state['messages'] = count
    text = _player_line(ctx)
    if not profiles or not text or mode() != 'full':
        return ''
    budget = lore_budget() // len(profiles)
    lines = []
    for p in profiles:
        facts = L.lookup(text, p, budget, world={'quests': world().get('quests') or {}}, sent=_state['sent'])
        # what the NPC's own block already says needs no lore line (rule: never send what the prompt has)
        facts = [f for f in facts if f.split(' is ')[0] not in _state.get('knows', '')]
        if facts:
            lines.append(f"(What {p.get('name')} knows about this: {' '.join(facts)})")
            logging.getLogger('Mantella').log(23, f"Knowledge: {len(facts)} lore line(s) for {p.get('name')}")
    return '\n'.join(lines)
