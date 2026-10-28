"""What each NPC knows, written from their own in-game dialogue (table npc_knows in lore.sqlite, built by
tools/build_knows.py). Lines tied to a quest are used only in the matching state of that quest, read from the World
module's world.json ("quest_state": 0 not started, 1 running, 2 done). Without World, only the untied lines are used.
Never raises: any problem gives no lines."""
import os
import sqlite3
import threading

from . import lore as L

STATE_OK = {'not_started': {0}, 'running': {1}, 'done': {2}, 'not_done': {0, 1}}
_con = {'path': None, 'con': None}
_lock = threading.Lock()


def reset():
    with _lock:
        if _con['con'] is not None:
            _con['con'].close()
        _con.update(path=None, con=None)


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
                else:
                    con.close()
        return _con['con']


def _rows(name, base_id, db_path):
    con = _db(db_path or L.default_db_path())
    if con is None or not name:
        return []
    with _lock:
        rows = con.execute("SELECT base_id, quest, state, seq, text FROM npc_knows WHERE npc = ? ORDER BY seq",
                           (name.lower(),)).fetchall()
    # Several NPCs can share a name: prefer this base id's rows, else the first one's
    ids = {r[0] for r in rows}
    want = (base_id or '').upper()
    pick = want if want in ids else (sorted(ids)[0] if ids else '')
    return [r[1:] for r in rows if r[0] == pick]


def knows_lines(name, base_id, quest_states, db_path=None):
    """The NPC's lines for the current quest states ({quest: 0|1|2}, or None without World). No secret line."""
    try:
        out = []
        for quest, state, _, text in _rows(name, base_id, db_path):
            if state == 'secret':
                continue
            if not quest:
                out.append(text)
            elif quest_states and quest in quest_states and quest_states[quest] in STATE_OK.get(state, set()):
                out.append(text)
        return out
    except Exception:  # noqa: BLE001 - knowledge is optional, never break the reply
        return []


def knows_block(name, base_id, quest_states, db_path=None):
    """The block for the system prompt: what the NPC knows, and their secret, or '' when there is nothing."""
    try:
        lines = knows_lines(name, base_id, quest_states, db_path)
        secret = [t for _, s, _, t in _rows(name, base_id, db_path) if s == 'secret']
        if not lines and not secret:
            return ''
        text = f"What {name} knows (and nothing beyond it about these matters):\n" + '\n'.join(f"- {l}" for l in lines)
        if secret:
            text += f"\n- Secret: {secret[0]}"
        return text
    except Exception:  # noqa: BLE001
        return ''
