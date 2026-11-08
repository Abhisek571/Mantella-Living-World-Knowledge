"""Load the NPC "what I know" blocks (work/knows_out/*.json, written to tools/knows_spec.md) into data/lore.sqlite
(table npc_knows), after checking them, and write the quest list the World module tracks for them
(SKSE/Plugins/StorageUtilData/MantellaLivingWorld/knowledge_quests.json, JsonUtil format).

usage: python tools/build_knows.py        Only stdlib."""
import glob
import json
import os
import re
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATES = {'not_started', 'running', 'done', 'not_done', 'started'}
# a second condition on a row: another quest's state, or the side the player took in the civil war (World's war_side)
WAR_SIDES = {'Legion', 'Stormcloaks'}
# UESP names a quest's pointer (the rumour that starts it); the pointer stops once the real quest starts, so rows are
# tied to the real quest, with the pointer's states moved where they differ
POINTER_QUESTS = {'MS10MiscObjPointer': ('MS10', {}), 'DA08RumorPointer': ('DA08', {'running': 'not_done'})}
# the Dragonborn stage and who knows the player as the Dragonborn (server/lw_knowledge/dragonborn.py), Helgen and the
# end of the civil war (hookup.HELGEN_QUESTS and WAR_END_QUEST, common knowledge)
ALWAYS_TRACKED = ('MQ101', 'MQ102', 'MQ104', 'MQ105', 'MQ106', 'MQ203', 'MQ204', 'MQ303', 'CWFinale')
MAX_ALWAYS, MAX_WHEN, MAX_WHEN_LINES, MAX_WORDS = 6, 4, 3, 35
# Words that mean the line is about the game, not the world
META = re.compile(r'\b(quest|(?<!lute )(?<!flute )(?<!drum )player|NPC|the game|XP|level up)\b', re.I)  # a lute player is fine


def tokens(text):
    return (len(text) + 3) // 4


def good_line(text, max_words=MAX_WORDS):
    return isinstance(text, str) and text.strip() and len(text.split()) <= max_words and not META.search(text)


def also_ok(also_quest, also_state, quest_ids):
    if not also_quest:
        return not also_state
    if also_quest == 'war_side':
        return also_state in WAR_SIDES
    return (also_quest in quest_ids or also_quest in REAL_QUESTS) and also_state in STATES


REAL_QUESTS = {real for real, _ in POINTER_QUESTS.values()}


def real_quest(quest, state):
    real, states = POINTER_QUESTS.get(quest, (quest, {}))
    return real, states.get(state, state)


def rows_for(block, quest_ids):
    """(rows, rejected count) for one block; a bad line or entry is dropped, the rest kept. A row is
    (npc, base_id, quest, state, seq, text, also_quest, also_state)."""
    rows, rejected = [], 0
    name, base_id = block.get('name', '').strip(), (block.get('base_id') or '').upper()
    if not name:
        return [], 1
    for i, line in enumerate((block.get('always') or [])[:MAX_ALWAYS]):
        if good_line(line):
            rows.append((name.lower(), base_id, '', '', i, line.strip(), '', ''))
        else:
            rejected += 1
    # an "always" line that only holds at one quest stage (knows_fixes.json 'tie'): one row per stage it holds at
    for k, (line, ties) in enumerate(block.get('tied') or []):
        for quest, state in ties:
            secret = state.startswith('secret:')
            if quest not in quest_ids or (state[7:] if secret else state) not in STATES or not good_line(line):
                rejected += 1
            else:
                rows.append((name.lower(), base_id, quest, state, (900 if secret else 50) + k, line.strip(), '', ''))
    for j, entry in enumerate((block.get('when') or [])[:MAX_WHEN]):
        quest, state = entry.get('quest', ''), entry.get('state', '')
        also_quest, also_state = entry.get('also_quest', ''), entry.get('also_state', '')
        if quest not in quest_ids or state not in STATES or not also_ok(also_quest, also_state, quest_ids):
            rejected += 1
            continue
        quest, state = real_quest(quest, state)
        for k, line in enumerate((entry.get('lines') or [])[:MAX_WHEN_LINES]):
            if good_line(line, MAX_WORDS + 15):  # stage lines carry a little more context
                rows.append((name.lower(), base_id, quest, state, 100 + j * 10 + k, line.strip(), also_quest, also_state))
            else:
                rejected += 1
    secret = block.get('secret') or ''
    if secret:
        # a secret that only holds at one quest stage keeps that stage: state 'secret:<state>' with its quest
        quest, state = block.get('secret_quest', ''), block.get('secret_state', '')
        if quest and (quest not in quest_ids or state not in STATES):
            rejected += 1
        elif isinstance(secret, str) and len(secret.split()) <= 40:
            rows.append((name.lower(), base_id, quest, f'secret:{state}' if quest else 'secret', 900, secret.strip(), '', ''))
        else:
            rejected += 1
    return rows, rejected


def merge_blocks(files):
    """One block per NPC (name + base_id) from lists of blocks in file order; a later file's block replaces an earlier
    one (long_*.json redoes the NPCs whose wiki dialogue was cut off in their batch)."""
    merged = {}
    for blocks in files:
        for block in blocks:
            merged[(block.get('name', '').strip().lower(), (block.get('base_id') or '').upper())] = block
    return list(merged.values())


def apply_fixes(blocks, fixes):
    """Blocks with the hand corrections of tools/knows_fixes.json: a 'when' entry tied to the wrong quest stage is moved
    to the right one, a secret that only holds at one quest stage is tied to it ('secret'), an "always" line is tied
    to the quest stages it holds at ('tie': the line that starts with 'starts', a list of [quest, state]; state
    'secret:<state>' keeps it as a secret then), and a 'when' entry gets a second condition ('also': also_quest +
    also_state; also_quest 'war_side' with 'Legion' or 'Stormcloaks' is the player's side). Returns the number of
    entries changed."""
    moved = 0
    for fix in fixes.get('tie', []):
        for block in blocks:
            if block.get('name', '').strip().lower() != fix['name'].lower():
                continue
            for line in list(block.get('always') or []):
                if isinstance(line, str) and line.startswith(fix['starts']):
                    block['always'].remove(line)
                    block.setdefault('tied', []).append((line, [tuple(t) for t in fix['states']]))
                    moved += 1
    for fix in fixes.get('also', []):
        for block in blocks:
            if block.get('name', '').strip().lower() != fix['name'].lower():
                continue
            for entry in block.get('when') or []:
                if entry.get('quest') == fix['quest'] and entry.get('state') == fix['state']:
                    entry['also_quest'], entry['also_state'] = fix['also_quest'], fix['also_state']
                    moved += 1
    for fix in fixes.get('secret', []):
        for block in blocks:
            if block.get('name', '').strip().lower() == fix['name'].lower() and block.get('secret'):
                block['secret_quest'], block['secret_state'] = fix['quest'], fix['state']
                moved += 1
    for fix in fixes.get('retag', []):
        for block in blocks:
            if block.get('name', '').strip().lower() != fix['name'].lower():
                continue
            for entry in block.get('when') or []:
                if entry.get('quest') == fix['quest'] and entry.get('state') == fix['state']:
                    entry['quest'], entry['state'] = fix['to_quest'], fix['to_state']
                    moved += 1
    return moved


def load_blocks(blocks, db_path, quest_ids):
    con = sqlite3.connect(db_path)
    con.execute("DROP TABLE IF EXISTS npc_knows")
    con.execute("CREATE TABLE npc_knows (npc TEXT NOT NULL, base_id TEXT, quest TEXT, state TEXT, seq INTEGER, "
                "text TEXT NOT NULL, tokens INTEGER, also_quest TEXT, also_state TEXT)")
    report = {'npcs': 0, 'rows': 0, 'rejected': 0}
    for block in blocks:
        rows, rejected = rows_for(block, quest_ids)
        report['rejected'] += rejected
        if rows:
            report['npcs'] += 1
            report['rows'] += len(rows)
            con.executemany("INSERT INTO npc_knows VALUES (?,?,?,?,?,?,?,?,?)",
                            [r[:6] + (tokens(r[5]),) + r[6:] for r in rows])
    con.execute("CREATE INDEX IF NOT EXISTS npc_knows_npc ON npc_knows(npc)")
    con.commit()
    con.close()
    return report


def write_quest_list(db_path, out_path):
    con = sqlite3.connect(db_path)
    quests = {q for (q,) in con.execute("SELECT DISTINCT quest FROM npc_knows WHERE quest != ''")}
    quests |= {q for (q,) in con.execute("SELECT DISTINCT also_quest FROM npc_knows WHERE also_quest NOT IN ('', 'war_side')")}
    quests = sorted(quests | set(ALWAYS_TRACKED))
    con.close()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'stringList': {'quests': quests}}, f, indent=1)
    return quests


def main():
    quest_ids = set(json.load(open(os.path.join(ROOT, 'data', 'quest_ids.json'), encoding='utf-8')).values())
    paths = sorted(glob.glob(os.path.join(ROOT, 'work', 'knows_out', '*.json')), key=lambda p: os.path.basename(p).startswith('long_'))
    blocks = merge_blocks(json.load(open(path, encoding='utf-8')) for path in paths)
    apply_fixes(blocks, json.load(open(os.path.join(ROOT, 'tools', 'knows_fixes.json'), encoding='utf-8')))
    report =load_blocks(blocks, os.path.join(ROOT, 'data', 'lore.sqlite'), quest_ids)
    quests = write_quest_list(os.path.join(ROOT, 'data', 'lore.sqlite'),
                              os.path.join(ROOT, 'SKSE', 'Plugins', 'StorageUtilData', 'MantellaLivingWorld', 'knowledge_quests.json'))
    print(f"{report['npcs']} NPCs, {report['rows']} lines, {report['rejected']} rejected, {len(quests)} quests tracked")


if __name__ == '__main__':
    main()
