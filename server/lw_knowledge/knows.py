"""What each NPC knows, written from their own in-game dialogue (table npc_knows in lore.sqlite, built by
tools/build_knows.py). Lines tied to a quest are used only in the matching state of that quest, read from the World
module's world.json ("quest_state": 0 not started, 1 running, 2 done). Without World, only the untied lines are used.
A secret row has state 'secret', or 'secret:<state>' with a quest when it only holds at that stage. A row may carry a
second condition (also_quest, also_state): another quest's state, or 'war_side' with the side the player took
('Legion' or 'Stormcloaks', World's war_side, passed in quest_states['war_side']).
Never raises: any problem gives no lines."""
import os
import sqlite3
import threading

from . import lore as L

STATE_OK = {'not_started': {0}, 'running': {1}, 'done': {2}, 'not_done': {0, 1}, 'started': {1, 2}}
_con = {'path': None, 'con': None, 'also': False}
_lock = threading.Lock()


def reset():
    with _lock:
        if _con['con'] is not None:
            _con['con'].close()
        _con.update(path=None, con=None, also=False)


def _db(path):
    with _lock:
        if _con['path'] != path:
            if _con['con'] is not None:
                _con['con'].close()
            _con.update(path=path, con=None)
            if os.path.exists(path):
                con = sqlite3.connect("file:" + path.replace("\\", "/") + "?mode=ro", uri=True, check_same_thread=False)
                if con.execute("SELECT name FROM sqlite_master WHERE name='npc_knows'").fetchone():
                    _con['con'] = con
                    _con['also'] = any(r[1] == 'also_quest' for r in con.execute("PRAGMA table_info(npc_knows)"))
                else:
                    con.close()
        return _con['con']


def _rows(name, base_id, db_path):
    con = _db(db_path or L.default_db_path())
    if con is None or not name:
        return []
    with _lock:
        also = "ifnull(also_quest, ''), ifnull(also_state, '')" if _con['also'] else "'', ''"
        rows = con.execute(f"SELECT base_id, quest, state, seq, text, {also} FROM npc_knows WHERE npc = ? ORDER BY seq",
                           (name.lower(),)).fetchall()
    # Several NPCs can share a name: prefer this base id's rows, else the first one's
    ids = {r[0] for r in rows}
    want = (base_id or '').upper()
    pick = want if want in ids else (sorted(ids)[0] if ids else '')
    return [r[1:] for r in rows if r[0] == pick]


def _stage_ok(quest, state, quest_states):
    return bool(quest_states) and quest in quest_states and quest_states[quest] in STATE_OK.get(state, set())


def _also_ok(also_quest, also_state, quest_states):
    if not also_quest:
        return True
    if also_quest == 'war_side':
        return bool(quest_states) and quest_states.get('war_side') == also_state
    return _stage_ok(also_quest, also_state, quest_states)


def knows_lines(name, base_id, quest_states, db_path=None):
    """The NPC's lines for the current quest states ({quest: 0|1|2}, or None without World). No secret line."""
    try:
        out = []
        for quest, state, _, text, also_quest, also_state in _rows(name, base_id, db_path):
            if state.startswith('secret') or not _also_ok(also_quest, also_state, quest_states):
                continue
            if not quest:
                out.append(text)
            elif _stage_ok(quest, state, quest_states):
                out.append(text)
        return out
    except Exception:  # noqa: BLE001 - knowledge is optional, never break the reply
        return []


def knows_block(name, base_id, quest_states, db_path=None, speakers=1):
    """The block for the system prompt: what the NPC knows, and their secret, or '' when there is nothing.
    speakers: how many NPCs share this talk; with others there, the secret is marked as never said in front of them."""
    try:
        lines = knows_lines(name, base_id, quest_states, db_path)
        secret = [t for q, s, _, t, _, _ in _rows(name, base_id, db_path) if s == 'secret'
                  or (s.startswith('secret:') and _stage_ok(q, s[7:], quest_states))]
        if not lines and not secret:
            return ''
        text = f"What {name} knows (and nothing beyond it about these matters):\n" + '\n'.join(f"- {l}" for l in lines)
        if secret:
            label = f"Secret only {name} knows; never said in front of the others here" if speakers > 1 else "Secret"
            text += f"\n- {label}: {' '.join(secret)}"
        return text
    except Exception:  # noqa: BLE001
        return ''
